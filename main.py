import sys
import threading
import time
import mss
import numpy as np
import onnxruntime as ort
import cv2
import logging
import ctypes
from ctypes import wintypes

# ========== Windows API 定义 ==========
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def send_mouse_relative(dx, dy):
    if dx == 0 and dy == 0:
        return
    input_struct = INPUT()
    input_struct.type = INPUT_MOUSE
    input_struct.union.mi.dx = dx
    input_struct.union.mi.dy = dy
    input_struct.union.mi.dwFlags = MOUSEEVENTF_MOVE
    input_struct.union.mi.time = 0
    input_struct.union.mi.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))


def send_mouse_left_down():
    input_struct = INPUT()
    input_struct.type = INPUT_MOUSE
    input_struct.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))


def send_mouse_left_up():
    input_struct = INPUT()
    input_struct.type = INPUT_MOUSE
    input_struct.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
    ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))


def get_mouse_position():
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def is_left_button_pressed():
    """检测左键是否被物理按下（忽略模拟输入）"""
    return (ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000) != 0


# ========== 日志配置 ==========
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/app.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


logger = setup_logging()

# ========== 屏幕参数 ==========
ORIGINAL_WIDTH = 1920
ORIGINAL_HEIGHT = 1080

# ========== 触发区域（原始屏幕坐标）==========
TRIGGER_X_MIN = 853
TRIGGER_Y_MIN = 873


def should_trigger_aim(target_x, target_y):
    """触发条件：目标在屏幕有效区域内（排除屏幕中心±100的玩家自身区域）"""
    outside_center_x = (target_x > TRIGGER_X_MIN + 10) or (target_x < TRIGGER_X_MIN - 10)
    outside_center_y = (target_y > TRIGGER_Y_MIN + 10) or (target_y < TRIGGER_Y_MIN - 10)
    return outside_center_x and outside_center_y


# ========== ONNX 模型参数 ==========
MODEL_PATH = 'PUBGV8S_640.onnx'
MODEL_INPUT_SIZE = 640                       # 模型输入尺寸 640×640
NUM_CLASSES = 2                              # 输出通道数 6 = 4(bbox) + 2(cls)
CONF_THRESHOLD = 0.4                         # 置信度阈值
IOU_THRESHOLD = 0.45                         # NMS IoU 阈值

# 坐标缩放比例 & padding：由 letterbox 动态计算，这里声明为全局变量
scale_ratio = 1.0         # letterbox 缩放比
pad_left = 0              # letterbox 左右 padding
pad_top = 0               # letterbox 上下 padding

# ========== 异步保存图片（避免阻塞主循环）==========
_save_queue = []
_save_lock = threading.Lock()


def _async_saver_thread():
    """后台线程保存图片，不阻塞主循环"""
    import os
    while True:
        time.sleep(0.001)
        with _save_lock:
            if not _save_queue:
                continue
            path, img = _save_queue.pop(0)
        try:
            cv2.imwrite(path, img)
        except Exception:
            pass


def schedule_save(path, img):
    """非阻塞：将图片加入保存队列"""
    with _save_lock:
        if len(_save_queue) < 5:
            _save_queue.append((path, img.copy()))


# 启动保存线程
threading.Thread(target=_async_saver_thread, daemon=True).start()

# ========== 跳帧参数 ==========
DETECT_EVERY_N_FRAMES = 1
frame_counter = 0

# ========== 鼠标移动（平滑多步 + 加速度补偿）==========
MOUSE_SPEED_MULTIPLIER = 1.5
SMOOTH_STEPS = 4
STEP_DELAY = 0.001


def aim_at_target(screen_center_x, screen_center_y, target_center_x, target_center_y,
                  hold_duration=0.05):
    """平滑多步移动 + 速度补偿，提高精准度"""
    delta_x = int((target_center_x - screen_center_x) * MOUSE_SPEED_MULTIPLIER)
    delta_y = int((target_center_y - screen_center_y) * MOUSE_SPEED_MULTIPLIER)

    if abs(delta_x) < 2 and abs(delta_y) < 2:
        return

    step_x = delta_x / SMOOTH_STEPS
    step_y = delta_y / SMOOTH_STEPS

    for i in range(SMOOTH_STEPS):
        if i == SMOOTH_STEPS - 1:
            cur_x = delta_x - int(step_x * (SMOOTH_STEPS - 1))
            cur_y = delta_y - int(step_y * (SMOOTH_STEPS - 1))
        else:
            cur_x = int(step_x)
            cur_y = int(step_y)

        if cur_x != 0 or cur_y != 0:
            send_mouse_relative(cur_x, cur_y)
        time.sleep(STEP_DELAY)

    # send_mouse_left_down()
    # time.sleep(hold_duration)
    # send_mouse_left_up()


# ========== ONNX 预处理 ==========
def letterbox(img, new_shape=(640, 640), color=(114, 114, 114)):
    """
    保持宽高比缩放并居中填充到目标尺寸（不拉伸、不裁剪）。
    img: (H, W, 3) uint8 ndarray
    返回: (padded_img, ratio, (pad_w, pad_h))
      - padded_img: 填充后的图像 (new_shape[0], new_shape[1], 3)
      - ratio: 缩放比 (new / old)
      - pad_w, pad_h: 左右和上下的 padding 像素数
    """
    shape = img.shape[:2]  # (H, W)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
    dw = (new_shape[1] - new_unpad[0]) / 2.0   # 左右各半
    dh = (new_shape[0] - new_unpad[1]) / 2.0   # 上下各半
    if (shape[1], shape[0]) != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top = int(round(dh - 0.1))
    bottom = int(round(dh + 0.1))
    left = int(round(dw - 0.1))
    right = int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right,
                             cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def preprocess(img_bgr):
    """
    预处理：letterbox 保持原图宽高比，不拉伸，返回 ONNX 输入 tensor。
    img_bgr: (H, W, 3) uint8 ndarray (原始 1080×1920)
    返回: (img_batch, img_640, ratio, (pad_w, pad_h))
    """
    global scale_ratio, pad_left, pad_top
    img_640, ratio, (pad_w, pad_h) = letterbox(
        img_bgr, (MODEL_INPUT_SIZE, MODEL_INPUT_SIZE))
    scale_ratio = ratio
    pad_left = pad_w
    pad_top = pad_h
    # BGR → RGB → CHW → float32 → /255 → batch
    img_rgb = img_640[:, :, ::-1]
    img_chw = np.transpose(img_rgb, (2, 0, 1)).astype(np.float32) / 255.0
    img_batch = np.expand_dims(img_chw, axis=0)
    return img_batch, img_640


# ========== ONNX 后处理 ==========
def postprocess(output, conf_threshold=CONF_THRESHOLD, iou_threshold=IOU_THRESHOLD):
    """
    解析 YOLOv8 ONNX 输出，执行 NMS，返回检测列表。
    output: (1, 6, 8400) float32 ndarray — [cx, cy, w, h, cls0_score, cls1_score]
    返回: [(x1, y1, x2, y2, conf, cls_id), ...] 坐标在 640×640 空间内
    """
    # 转置为 (8400, 6)
    preds = np.transpose(output[0], (1, 0))  # (8400, 6)

    # 提取各分量
    cx = preds[:, 0]
    cy = preds[:, 1]
    w = preds[:, 2]
    h = preds[:, 3]
    cls_scores = preds[:, 4:6]  # (8400, 2)

    # 每个 anchor 取最高分类置信度
    max_cls_conf = np.max(cls_scores, axis=1)   # (8400,)
    cls_ids = np.argmax(cls_scores, axis=1)      # (8400,)

    # 过滤低置信度
    mask = max_cls_conf >= conf_threshold
    if not np.any(mask):
        return []

    cx = cx[mask]
    cy = cy[mask]
    w = w[mask]
    h = h[mask]
    scores = max_cls_conf[mask]
    cls_ids = cls_ids[mask]

    # cx,cy,w,h → x1,y1,x2,y2
    x1 = cx - w / 2.0
    y1 = cy - h / 2.0
    x2 = cx + w / 2.0
    y2 = cy + h / 2.0

    # 裁剪到 [0, 640] 范围内
    x1 = np.clip(x1, 0, MODEL_INPUT_SIZE)
    y1 = np.clip(y1, 0, MODEL_INPUT_SIZE)
    x2 = np.clip(x2, 0, MODEL_INPUT_SIZE)
    y2 = np.clip(y2, 0, MODEL_INPUT_SIZE)

    # 过滤无效框
    valid = (x2 > x1 + 2) & (y2 > y1 + 2)
    if not np.any(valid):
        return []

    boxes = np.stack([x1, y1, x2, y2], axis=1)[valid]
    scores = scores[valid]
    cls_ids = cls_ids[valid]

    # NMS
    indices = cv2.dnn.NMSBoxes(
        bboxes=boxes.tolist(),
        scores=scores.tolist(),
        score_threshold=conf_threshold,
        nms_threshold=iou_threshold,
    )
    # cv2.dnn.NMSBoxes 返回的是 list of list 或空 tuple
    if len(indices) == 0:
        return []

    # flatten indices
    if isinstance(indices, tuple):
        # OpenCV 4.5+ returns a tuple of arrays
        keep = indices[0].flatten() if len(indices) > 0 else []
    else:
        keep = np.array(indices).flatten()

    if len(keep) == 0:
        return []

    detections = []
    for i in keep:
        i = int(i)
        detections.append((
            float(boxes[i][0]), float(boxes[i][1]),
            float(boxes[i][2]), float(boxes[i][3]),
            float(scores[i]), int(cls_ids[i]),
        ))

    return detections


# ========== 主程序 ==========
def main():
    # 加载 ONNX 模型（优先 GPU：CUDA → DirectML → CPU 兜底）
    logger.info(f"加载 ONNX 模型: {MODEL_PATH}")
    gpu_providers = [
        ('CUDAExecutionProvider', {'device_id': 0}),
        'DmlExecutionProvider',            # DirectML，兼容 AMD / NVIDIA / Intel
        'CPUExecutionProvider',
    ]
    session = None
    for provider in gpu_providers:
        try:
            session = ort.InferenceSession(MODEL_PATH, providers=[provider])
            actual_provider = session.get_providers()[0]
            logger.info(f"✓ 使用推理后端: {actual_provider}")
            break
        except Exception as e:
            logger.warning(f"✗ {provider} 不可用: {e}")
            continue
    if session is None:
        raise RuntimeError("无可用的推理后端（已尝试 CUDA / DirectML / CPU）")

    input_name = session.get_inputs()[0].name
    logger.info(f"模型输入: {input_name} {session.get_inputs()[0].shape}")
    logger.info(f"模型输出: {session.get_outputs()[0].name} {session.get_outputs()[0].shape}")

    screen_center_x, screen_center_y = ORIGINAL_WIDTH // 2, ORIGINAL_HEIGHT // 2
    monitor = {'top': 0, 'left': 0, 'width': ORIGINAL_WIDTH, 'height': ORIGINAL_HEIGHT}

    print("=" * 60)
    print("PUBG_v8s.onnx 模型已加载")
    print(f"开始屏幕监控，按 'q' 退出...")
    print(f"触发区域: X={TRIGGER_X_MIN} Y={TRIGGER_Y_MIN} | 模型输入: {MODEL_INPUT_SIZE}×{MODEL_INPUT_SIZE}")
    print("=" * 60)

    target_counter = 0
    last_aim_time = 0
    aim_cooldown = 0.01
    global frame_counter

    with mss.mss() as sct:
        while True:
            try:
                # 截图
                sct_img = sct.grab(monitor)
                # mss 返回 BGRA 4通道，取 BGR 3通道
                img = np.array(sct_img)[:, :, :3].copy()

                # 跳帧逻辑
                frame_counter += 1
                if frame_counter % DETECT_EVERY_N_FRAMES != 0:
                    continue

                # ONNX 预处理 + 推理
                img_input, img_640 = preprocess(img)
                outputs = session.run(None, {input_name: img_input})
                detections = postprocess(outputs[0])

                current_time = time.time()

                for det in detections:
                    x1, y1, x2, y2, conf, cls_id = det

                    # 过滤过小的目标（在 640 空间内 < 10px 宽或 < 20px 高）
                    w_det = x2 - x1
                    h_det = y2 - y1
                    if w_det < 10 or h_det < 20:
                        continue

                    # 坐标从 640×640 还原到 1920×1080（letterbox：去 padding 再除缩放比）
                    cx_orig = int(((x1 + x2) / 2 - pad_left) / scale_ratio)
                    cy_orig = int(((y1 + y2) / 2 - pad_top) / scale_ratio)

                    if should_trigger_aim(cx_orig, cy_orig):
                        if current_time - last_aim_time >= aim_cooldown:
                            target_counter += 1
                            logger.info(
                                f"{target_counter}.jpg - 目标中心:({cx_orig},{cy_orig}) "
                                f"置信度:{conf:.2f} 类别:{cls_id}"
                            )

                            # 异步保存图片 — 使用 640×640 模型原生尺寸
                            x1_int = int(x1)
                            y1_int = int(y1)
                            x2_int = int(x2)
                            y2_int = int(y2)
                            cx_640 = int((x1 + x2) / 2)
                            cy_640 = int((y1 + y2) / 2)

                            cv2.rectangle(img_640, (x1_int, y1_int),
                                          (x2_int, y2_int), (0, 255, 0), 2)
                            cv2.putText(img_640, f'{conf:.2f} c{cls_id}',
                                        (x1_int, max(y1_int - 5, 10)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                            cv2.circle(img_640, (cx_640, cy_640), 3, (0, 0, 255), -1)
                            schedule_save(f"{target_counter}.jpg", img_640)

                            aim_at_target(screen_center_x, screen_center_y, cx_orig, cy_orig)

                            last_aim_time = current_time
                            break  # 一次只处理一个目标

                # 按 q 退出
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            except KeyboardInterrupt:
                print("\n用户中断")
                break
            except Exception as e:
                logger.error(f"处理错误: {e}")
                continue

    cv2.destroyAllWindows()
    print("程序退出")


if __name__ == "__main__":
    main()
