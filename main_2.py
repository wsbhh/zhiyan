import sys
import threading
import time
import mss
import numpy as np
from ultralytics import YOLO
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

# ========== 优化：触发区域（原始屏幕坐标）==========
# 只检测屏幕右下角的一个区域，例如 x>1400, y>800
TRIGGER_X_MIN = 853
TRIGGER_Y_MIN = 873

def should_trigger_aim(target_x, target_y):
    """更严格的触发：目标必须在指定矩形内"""
    return (target_x > TRIGGER_X_MIN+100 or target_x < TRIGGER_X_MIN-100) and (target_y > TRIGGER_Y_MIN +100 or target_y < TRIGGER_Y_MIN -100)

# ========== 优化：检测图像缩放参数 ==========
ORIGINAL_WIDTH = 1920
ORIGINAL_HEIGHT = 1080
DETECT_WIDTH = 320                     # 降低分辨率提升速度（原640）
DETECT_HEIGHT = int(DETECT_WIDTH * ORIGINAL_HEIGHT / ORIGINAL_WIDTH)  # 180
SCALE_X = ORIGINAL_WIDTH / DETECT_WIDTH
SCALE_Y = ORIGINAL_HEIGHT / DETECT_HEIGHT

# 模型加载为半精度（FP16），推理更快（需要CUDA）

# ========== 优化：异步保存图片（避免阻塞主循环）==========
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
        if len(_save_queue) < 5:  # 限制队列长度
            _save_queue.append((path, img.copy()))  # copy避免共享内存


# 启动保存线程
threading.Thread(target=_async_saver_thread, daemon=True).start()

# ========== 优化：跳帧参数 ==========
DETECT_EVERY_N_FRAMES = 3   # 每3帧检测一次
frame_counter = 0

# ========== 鼠标移动（直接发送，最小延迟）==========

def aim_at_target(screen_center_x, screen_center_y, target_center_x, target_center_y,
                  hold_duration=0.1):
    """直接发送相对偏移，最小延迟"""
    delta_x = int(target_center_x - screen_center_x)
    delta_y = int(target_center_y - screen_center_y)

    # 直接发送，不经过线程
    send_mouse_relative(delta_x, delta_y)

    # 立即开枪（缩短按住时间）
    send_mouse_left_down()
    time.sleep(hold_duration)
    send_mouse_left_up()


# ========== 主程序（优化版） ==========
def main():
    model = YOLO('yolov8n.pt')

    screen_center_x, screen_center_y = ORIGINAL_WIDTH // 2, ORIGINAL_HEIGHT // 2
    monitor = {'top': 0, 'left': 0, 'width': ORIGINAL_WIDTH, 'height': ORIGINAL_HEIGHT}

    print("开始屏幕监控，按 'q' 退出...")
    print(f"触发区域: X={TRIGGER_X_MIN} Y={TRIGGER_Y_MIN} | 检测分辨率: {DETECT_WIDTH}x{DETECT_HEIGHT}")
    print("=" * 60)

    target_counter = 0
    last_aim_time = 0
    aim_cooldown = 1.0  # 降低冷却时间（原1.5）
    global frame_counter

    with mss.mss() as sct:
        while True:
            try:
                # 截图
                sct_img = sct.grab(monitor)
                # mss返回BGRA 4通道，YOLO需要3通道，直接切片去掉alpha通道
                img = np.array(sct_img)[:, :, :3].copy()

                # 跳帧逻辑
                frame_counter += 1
                if frame_counter % DETECT_EVERY_N_FRAMES != 0:
                    continue

                # 缩放图像（INTER_NEAREST最快）
                img_small = cv2.resize(img, (DETECT_WIDTH, DETECT_HEIGHT), interpolation=cv2.INTER_NEAREST)
                results = model(img_small, verbose=False)  # 关闭日志输出

                current_time = time.time()

                for result in results:
                    if result.boxes is None:
                        continue
                    for box in result.boxes:
                        if int(box.cls[0]) != 0:   # 只检测 person
                            continue
                        # 获取缩放图上的坐标
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0])
                        if conf < 0.4:
                            continue
                        w_small = x2 - x1
                        h_small = y2 - y1
                        if w_small < 15 or h_small < 30:   # 对应原始尺寸约 >50px
                            continue
                        # 还原到原始坐标
                        cx = int((x1 + x2) / 2 * SCALE_X)
                        cy = int((y1 + y2) / 2 * SCALE_Y)

                        # 不再打印每个检测，只在触发时输出
                        if should_trigger_aim(cx, cy):
                            if current_time - last_aim_time >= aim_cooldown:
                                target_counter += 1
                                logger.info(f"{target_counter}.jpg - 目标中心:({cx},{cy}) 置信度:{conf:.2f}")

                                # 异步保存图片（不阻塞主循环）
                                cv2.rectangle(img, (int(x1*SCALE_X), int(y1*SCALE_Y)),
                                              (int(x2*SCALE_X), int(y2*SCALE_Y)), (0,255,0), 2)
                                cv2.putText(img, f'{conf:.2f}',
                                            (int(x1*SCALE_X), int(y1*SCALE_Y)-10),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                                cv2.circle(img, (cx, cy), 5, (0,0,255), -1)
                                schedule_save(f"{target_counter}.jpg", img)

                                aim_at_target(screen_center_x, screen_center_y, cx, cy)

                                last_aim_time = current_time
                                break  # 一次只处理一个目标

                # 按q退出（waitKey(0)不阻塞）
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