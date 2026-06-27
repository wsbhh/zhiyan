"""
键盘和鼠标操作工具库
所有函数独立可调用，无需依赖主程序类
"""
import ctypes
import ctypes.wintypes
import time


# ========== 鼠标操作 ==========

def 移动鼠标(x, y):
    """移动鼠标到指定屏幕坐标

    参数:
        x: 目标X坐标（像素）
        y: 目标Y坐标（像素）
    """
    screen_width = ctypes.windll.user32.GetSystemMetrics(0)
    screen_height = ctypes.windll.user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / screen_width)
    abs_y = int(y * 65535 / screen_height)
    ctypes.windll.user32.mouse_event(0x8001, abs_x, abs_y, 0, 0)


def 点击(x, y):
    """在指定坐标完成一次完整点击（移动+按下+松开）

    参数:
        x: 目标X坐标
        y: 目标Y坐标
    """
    移动鼠标(x, y)
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # 左键按下
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # 左键松开


def 鼠标相对移动(delta_x, delta_y):
    """鼠标从当前位置偏移指定距离

    参数:
        delta_x: X轴偏移量（正数向右，负数向左）
        delta_y: Y轴偏移量（正数向下，负数向上）
    """
    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    new_x = point.x + delta_x
    new_y = point.y + delta_y

    screen_width = ctypes.windll.user32.GetSystemMetrics(0)
    screen_height = ctypes.windll.user32.GetSystemMetrics(1)
    new_x = max(0, min(new_x, screen_width - 1))
    new_y = max(0, min(new_y, screen_height - 1))

    abs_x = int(new_x * 65535 / screen_width)
    abs_y = int(new_y * 65535 / screen_height)
    ctypes.windll.user32.mouse_event(0x8001, abs_x, abs_y, 0, 0)


def 拖动鼠标(start_x, start_y, end_x, end_y, hold_time=1.0):
    """按住鼠标从起点拖动到终点

    参数:
        start_x: 起始X坐标
        start_y: 起始Y坐标
        end_x: 终点X坐标
        end_y: 终点Y坐标
        hold_time: 按住后等待多久再开始拖动（秒），默认1秒
    """
    screen_width = ctypes.windll.user32.GetSystemMetrics(0)
    screen_height = ctypes.windll.user32.GetSystemMetrics(1)

    # 移动到起始位置
    移动鼠标(start_x, start_y)
    time.sleep(0.1)

    # 按下左键
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(hold_time)

    # 分20步拖动到目标
    steps = 20
    step_x = (end_x - start_x) / steps
    step_y = (end_y - start_y) / steps
    for i in range(steps):
        current_x = int(start_x + step_x * (i + 1))
        current_y = int(start_y + step_y * (i + 1))
        abs_x = int(current_x * 65535 / screen_width)
        abs_y = int(current_y * 65535 / screen_height)
        ctypes.windll.user32.mouse_event(0x8001 | 0x0002, abs_x, abs_y, 0, 0)
        time.sleep(0.02)

    # 松开左键
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


# ========== FPS视角转动（SendInput硬件模拟） ==========

# SendInput 结构体定义
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001


def FPS视角转动(delta_x, delta_y):
    """FPS游戏视角转动 - SendInput硬件级鼠标相对移动

    参数:
        delta_x: 水平偏移量（正数向右转，负数向左转）
        delta_y: 垂直偏移量（正数向下看，负数向上看）
    """
    print("瞬间转动视角")
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = int(delta_x)
    inp.union.mi.dy = int(delta_y)
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def FPS视角平滑转动(delta_x, delta_y, 步数=20, 间隔=0.01):
    """FPS游戏视角平滑转动 - 分多步完成，模拟真人手感

    参数:
        delta_x: 总水平偏移量（正数向右转，负数向左转）
        delta_y: 总垂直偏移量（正数向下看，负数向上看）
        步数: 分几步完成移动，默认20步
        间隔: 每步之间间隔秒数，默认0.01秒
    """
    print("慢慢转转动视角")
    step_x = delta_x / 步数
    step_y = delta_y / 步数
    for _ in range(步数):
        FPS视角转动(step_x, step_y)
        time.sleep(间隔)


# 灵敏度系数（1度角度 = 多少像素鼠标移动，需根据游戏内灵敏度调试）
FPS_灵敏度 = 17.2


def FPS转到目标视角(当前坐标, 目标坐标):
    """根据两组坐标字符串，计算视角差并执行转动

    参数:
        当前坐标: 如 "-14575.2,-19591.8,20.2------1.64,-34.24----0"
        目标坐标: 如 "-12261.8,-21207.5,148.2------0.14,22.16----0"
    """
    print("==========  FPS视角转动计算  ==========")

    # 解析当前坐标
    当前部分 = 当前坐标.split("-----")
    当前视角部分 = 当前部分[1].split("----")[0]
    当前pitch = float(当前视角部分.split(",")[0])
    当前yaw = float(当前视角部分.split(",")[1])
    print(f"当前视角  Pitch={当前pitch}  Yaw={当前yaw}")

    # 解析目标坐标
    目标部分 = 目标坐标.split("-----")
    目标视角部分 = 目标部分[1].split("----")[0]
    目标pitch = float(目标视角部分.split(",")[0])
    目标yaw = float(目标视角部分.split(",")[1])
    print(f"目标视角  Pitch={目标pitch}  Yaw={目标yaw}")

    # 计算角度差
    yaw差 = 目标yaw - 当前yaw
    pitch差 = 目标pitch - 当前pitch
    print(f"角度差    Yaw差={yaw差:.2f}  Pitch差={pitch差:.2f}")

    # 角度差 × 灵敏度 = 鼠标像素移动量（Pitch方向取反：游戏Pitch增大=抬头，鼠标dy需为负）
    delta_x = yaw差 * FPS_灵敏度
    delta_y = -(pitch差 * FPS_灵敏度)
    print(f"鼠标移动  delta_x={delta_x:.1f}  delta_y={delta_y:.1f}  (灵敏度={FPS_灵敏度})")

    # 执行瞬间转动
    FPS视角转动(delta_x, delta_y)
    print("========== 视角转动完成 ==========")


# ========== 键盘操作 ==========

# 虚拟键码映射表
VK_MAP = {
    "TAB": 0x09, "ENTER": 0x0D, "ESC": 0x1B, "SPACE": 0x20,
    "BACK": 0x08, "DELETE": 0x2E, "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "A": 0x41, "B": 0x42, "C": 0x43, "D": 0x44, "E": 0x45,
    "F": 0x46, "G": 0x47, "H": 0x48, "I": 0x49, "J": 0x4A,
    "K": 0x4B, "L": 0x4C, "M": 0x4D, "N": 0x4E, "O": 0x4F,
    "P": 0x50, "Q": 0x51, "R": 0x52, "S": 0x53, "T": 0x54,
    "U": 0x55, "V": 0x56, "W": 0x57, "X": 0x58, "Y": 0x59, "Z": 0x5A,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
    "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
    "F11": 0x7A, "F12": 0x7B,
}


def 按键(key):
    """按下并松开一个按键

    参数:
        key: 按键名称，如 "TAB", "SPACE", "E", "F1", "4" 等
    """
    key_upper = key.upper()
    if key_upper not in VK_MAP:
        print("未知按键：" + key)
        return
    vk_code = VK_MAP[key_upper]
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
    time.sleep(0.05)


def 长按按键(key, 持续时间=0.5):
    """按住一个按键指定时间后松开

    参数:
        key: 按键名称
        持续时间: 按住多少秒，默认0.5秒
    """
    key_upper = key.upper()
    if key_upper not in VK_MAP:
        print("未知按键：" + key)
        return
    vk_code = VK_MAP[key_upper]
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(持续时间)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
    time.sleep(0.05)


def 组合键(modifier, key):
    """按下组合键（如 ALT+D, CTRL+C）

    参数:
        modifier: 修饰键，如 "ALT", "CTRL", "SHIFT"
        key: 主按键，如 "D", "C", "V"
    """
    mod_upper = modifier.upper()
    key_upper = key.upper()
    if mod_upper not in VK_MAP:
        print("未知修饰键：" + modifier)
        return
    if key_upper not in VK_MAP:
        print("未知按键：" + key)
        return

    mod_code = VK_MAP[mod_upper]
    key_code = VK_MAP[key_upper]

    ctypes.windll.user32.keybd_event(mod_code, 0, 0, 0)   # 修饰键按下
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(key_code, 0, 0, 0)   # 主键按下
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(key_code, 0, 2, 0)   # 主键松开
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(mod_code, 0, 2, 0)   # 修饰键松开
    time.sleep(0.05)


def 输入文本(text):
    """模拟键盘逐字输入文本（英文统一大写输入）

    参数:
        text: 要输入的字符串
    """
    text = text.upper()
    vk_codes = {
        '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
        '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
        'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45,
        'F': 0x46, 'G': 0x47, 'H': 0x48, 'I': 0x49, 'J': 0x4A,
        'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F,
        'P': 0x50, 'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54,
        'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58, 'Y': 0x59, 'Z': 0x5A,
    }
    for char in text:
        if char in vk_codes:
            vk_code = vk_codes[char]
            need_shift = char.isupper()
            if need_shift:
                ctypes.windll.user32.keybd_event(0x10, 0, 0, 0)
                time.sleep(0.01)
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            time.sleep(0.01)
            ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
            time.sleep(0.01)
            if need_shift:
                ctypes.windll.user32.keybd_event(0x10, 0, 2, 0)
                time.sleep(0.01)
            time.sleep(0.05)
        else:
            print("无法输入字符：" + char)


# ========== 使用示例 ==========

if __name__ == "__main__":
    print("========== 操作工具使用示例 ==========")
    time.sleep(2)  # 等2秒切换到目标窗口

    # 鼠标操作示例
    # 移动鼠标(500, 300)
    # 点击(500, 300)
    # 鼠标相对移动(0, 500)
    # 拖动鼠标(500, 300, 800, 600, hold_time=1.0)

    # 键盘操作示例
    # 按键("TAB")
    # 按键("SPACE")
    # 按键("E")
    # 长按按键("W", 0.7)
    # 组合键("ALT", "D")
    # 组合键("CTRL", "C")
    # 输入文本("abc123")

    print("========== 示例结束 ==========")
