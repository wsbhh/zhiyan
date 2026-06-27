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

# 全局状态
lock_enabled = False
target_delta_x = 0
target_delta_y = 0
lock_thread = None
total_moved_x = 0
total_moved_y = 0

return_enabled = False
return_delta_x = 0
return_delta_y = 0
return_thread = None

holding = False
is_moving = False
movement_lock = threading.Lock()

# 速度参数
MAX_STEP = 100
SLEEP_TIME = 0.00001

# ========== 优化：触发区域（原始屏幕坐标）==========
# 只检测屏幕右下角的一个区域，例如 x>1400, y>800
TRIGGER_X_MIN = 853
TRIGGER_Y_MIN = 872

def should_trigger_aim(target_x, target_y):
    """更严格的触发：目标必须在指定矩形内"""
    return (target_x > TRIGGER_X_MIN+100 or target_x < TRIGGER_X_MIN-100) and (target_y > TRIGGER_Y_MIN +100 or target_y < TRIGGER_Y_MIN -100)
# ========== 优化：检测图像缩放参数 ==========
ORIGINAL_WIDTH = 1920
ORIGINAL_HEIGHT = 1080
DETECT_WIDTH = 640                     # 缩放后的宽度
DETECT_HEIGHT = int(DETECT_WIDTH * ORIGINAL_HEIGHT / ORIGINAL_WIDTH)  # 360
SCALE_X = ORIGINAL_WIDTH / DETECT_WIDTH
SCALE_Y = ORIGINAL_HEIGHT / DETECT_HEIGHT

# ========== 优化：跳帧参数 ==========
DETECT_EVERY_N_FRAMES = 3   # 每3帧检测一次
frame_counter = 0

# ========== 鼠标移动线程（未改动，保持原逻辑）==========
def continuous_lock_to_target():
    global lock_enabled, target_delta_x, target_delta_y, total_moved_x, total_moved_y, is_moving
    print("[移动到目标线程] 启动")
    with movement_lock:
        is_moving = True
    try:
        while lock_enabled:
            remaining_x = target_delta_x - total_moved_x
            remaining_y = target_delta_y - total_moved_y
            if abs(remaining_x) < 5 and abs(remaining_y) < 5:
                break
            step_x = max(-MAX_STEP, min(MAX_STEP, remaining_x))
            step_y = max(-MAX_STEP, min(MAX_STEP, remaining_y))
            if step_x == 0 and remaining_x != 0:
                step_x = 1 if remaining_x > 0 else -1
            if step_y == 0 and remaining_y != 0:
                step_y = 1 if remaining_y > 0 else -1
            if step_x != 0 or step_y != 0:
                send_mouse_relative(step_x, step_y)
                total_moved_x += step_x
                total_moved_y += step_y
            time.sleep(SLEEP_TIME)
    except Exception as e:
        print(f"[移动到目标线程] 错误: {e}")
    finally:
        with movement_lock:
            is_moving = False
        print(f"[移动到目标线程] 退出, 最终移动: ({total_moved_x}, {total_moved_y})")
        total_moved_x = 0
        total_moved_y = 0


def continuous_return_to_original():
    global return_enabled, return_delta_x, return_delta_y, total_moved_x, total_moved_y, is_moving
    print("[返回原始位置线程] 启动")
    with movement_lock:
        is_moving = True
    total_moved_x = 0
    total_moved_y = 0
    try:
        while return_enabled:
            remaining_x = return_delta_x - total_moved_x
            remaining_y = return_delta_y - total_moved_y
            if abs(remaining_x) < 5 and abs(remaining_y) < 5:
                break
            step_x = max(-MAX_STEP, min(MAX_STEP, remaining_x))
            step_y = max(-MAX_STEP, min(MAX_STEP, remaining_y))
            if step_x == 0 and remaining_x != 0:
                step_x = 1 if remaining_x > 0 else -1
            if step_y == 0 and remaining_y != 0:
                step_y = 1 if remaining_y > 0 else -1
            if step_x != 0 or step_y != 0:
                send_mouse_relative(step_x, step_y)
                total_moved_x += step_x
                total_moved_y += step_y
            time.sleep(SLEEP_TIME)
    except Exception as e:
        print(f"[返回原始位置线程] 错误: {e}")
    finally:
        with movement_lock:
            is_moving = False
        print(f"[返回原始位置线程] 退出, 最终移动: ({total_moved_x}, {total_moved_y})")


def continuous_hold_lock():
    global holding
    print("[固定位置线程] 启动")
    while holding:
        try:
            # 微小抖动防止准星偏移
            send_mouse_relative(1, 0)
            send_mouse_relative(-1, 0)
            send_mouse_relative(0, 1)
            send_mouse_relative(0, -1)
            time.sleep(0.01)
        except Exception as e:
            print(f"[固定位置线程] 错误: {e}")
            break
    print("[固定位置线程] 退出")


# ========== 瞄准流程 ==========
def quick_move_to_target(dx, dy, move_duration=0.1):
    global lock_enabled, target_delta_x, target_delta_y, lock_thread
    target_delta_x = dx
    target_delta_y = dy
    print(f"\n快速移动到目标偏移: ({dx}, {dy})")
    lock_enabled = True
    lock_thread = threading.Thread(target=continuous_lock_to_target, daemon=True)
    lock_thread.start()
    lock_thread.join(timeout=move_duration + 0.2)
    lock_enabled = False
    print("移动到目标完成")


def hold_at_target_and_click(hold_duration=1):
    global holding
    print(f"在目标位置固定并按住左键 {hold_duration} 秒")
    send_mouse_left_down()
    holding = True
    hold_thread = threading.Thread(target=continuous_hold_lock, daemon=True)
    hold_thread.start()
    time.sleep(hold_duration)
    send_mouse_left_up()
    holding = False
    hold_thread.join(timeout=0.5)
    print("固定位置操作完成")


def quick_return_to_original(dx, dy, return_duration=0.1):
    global return_enabled, return_delta_x, return_delta_y, return_thread
    return_delta_x = dx
    return_delta_y = dy
    print(f"快速返回原始位置偏移: ({dx}, {dy})")
    return_enabled = True
    return_thread = threading.Thread(target=continuous_return_to_original, daemon=True)
    return_thread.start()
    return_thread.join(timeout=return_duration + 0.2)
    return_enabled = False
    print("返回原始位置完成")


def aim_at_target(screen_center_x, screen_center_y, target_center_x, target_center_y,
                  move_duration=0.1, hold_duration=1, return_duration=0.1):
    try:
        delta_x = int(target_center_x - screen_center_x)
        delta_y = int(target_center_y - screen_center_y)
        print(f"\n完整瞄准流程：移动({delta_x}, {delta_y}) -> 按住{hold_duration}秒 -> 返回")
        quick_move_to_target(delta_x, delta_y, move_duration)
        # hold_at_target_and_click(hold_duration)
        # quick_return_to_original(-delta_x, -delta_y, return_duration)
    except Exception as e:
        print(f"[瞄准流程错误] {e}")
    finally:
        global is_moving, lock_enabled, return_enabled, holding
        with movement_lock:
            is_moving = False
        lock_enabled = False
        return_enabled = False
        holding = False


# ========== 主程序（优化版） ==========
def main():
    print("正在加载YOLO模型...")
    model = YOLO('yolov8n.pt')
    print("模型加载完成")

    screen_center_x, screen_center_y = ORIGINAL_WIDTH // 2, ORIGINAL_HEIGHT // 2
    monitor = {'top': 0, 'left': 0, 'width': ORIGINAL_WIDTH, 'height': ORIGINAL_HEIGHT}

    print("开始屏幕监控，按 'q' 退出...")
    print("提示：只有按住鼠标左键时才会进行目标检测和自动瞄准")
    print(f"触发区域: X > {TRIGGER_X_MIN} 且 Y > {TRIGGER_Y_MIN}")
    print(f"检测缩放: {ORIGINAL_WIDTH}x{ORIGINAL_HEIGHT} -> {DETECT_WIDTH}x{DETECT_HEIGHT} (坐标自动还原)")
    print(f"跳帧设置: 每 {DETECT_EVERY_N_FRAMES} 帧检测一次")
    print("=" * 60)

    target_counter = 0
    last_aim_time = 0
    aim_cooldown = 1.5
    global frame_counter

    with mss.mss() as sct:
        while True:
            try:
                # 鼠标移动或按住固定期间跳过检测
                with movement_lock:
                    if is_moving:
                        time.sleep(0.005)
                        continue

                # 未按下左键或正在模拟按住时跳过
                if not is_left_button_pressed() or holding:
                    time.sleep(0.02)  # 空闲时休眠稍长
                    continue

                # 截图
                sct_img = sct.grab(monitor)
                img = np.array(sct_img)
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                # 跳帧逻辑
                frame_counter += 1
                if frame_counter % DETECT_EVERY_N_FRAMES != 0:
                    continue

                # 缩放图像
                img_small = cv2.resize(img, (DETECT_WIDTH, DETECT_HEIGHT))
                results = model(img_small, verbose=False)

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
                                # 输出关键信息
                                print(f"\n>>> 目标 {target_counter} 触发瞄准 <<<")
                                print(f"  中心: ({cx}, {cy}) | 置信度: {conf:.2f}")
                                # 日志记录
                                logger.info(f"{target_counter}.jpg - 目标中心:({cx},{cy}) 置信度:{conf:.2f}")
                                # 可选：保存带标注的图片（按原始分辨率保存）
                                cv2.rectangle(img, (int(x1*SCALE_X), int(y1*SCALE_Y)),
                                              (int(x2*SCALE_X), int(y2*SCALE_Y)), (0,255,0), 2)
                                cv2.putText(img, f'person: {conf:.2f}',
                                            (int(x1*SCALE_X), int(y1*SCALE_Y)-10),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                                cv2.circle(img, (cx, cy), 5, (0,0,255), -1)
                                cv2.imwrite(f"{target_counter}.jpg", img)

                                original_x, original_y = get_mouse_position()
                                print(f"  移动前鼠标位置: ({original_x}, {original_y})")

                                aim_at_target(screen_center_x, screen_center_y, cx, cy,
                                              move_duration=0.1, hold_duration=1, return_duration=0.1)

                                last_aim_time = current_time
                                break  # 一次只处理一个目标

                # 按q退出（OpenCV 窗口用于显示，可选）
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