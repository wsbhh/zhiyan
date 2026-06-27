"""
============================================================
三角洲跑跑  v1.12
============================================================
组合：
  1) 跑点核心  ←  完整复制自 三角洲跑跑版本1.08.py 的「自动跑点」类与所有底层工具
  2) 中控通信  ←  test_script.py（注册 / 登录 / 申请账号 / 心跳 / 完成上报）
  3) UI 风格   ←  console_pyqt5.py（深色渐变 + 青色主题 + Microsoft YaHei）
  4) 目标动态完成  ←  1.11 新增：目标等级/金币/key 从服务器下发 + 封号检测

界面结构：
  ├ 登录页  → 账号 / 密码 / 登录 / 注册
  ├ 注册页  → 注册新账号 → 返回登录
  └ 主页    → 机器号 / 当前账号信息 / 启动 / 停止 / 日志

主线程：
  在【等级完成主流程】函数中已写好整套循环（申请账号 → 跑级 → 完成上报 → 下一个），
  支持服务器下发的目标等级/金币/key，自动判定达标或封号。
============================================================
"""
import base64
import ctypes
import os
import sys
import json
import math
import time
import random
import threading
import importlib.util  # 保留：避免你以后想再换回动态加载

import requests

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QSpinBox, QMessageBox,
    QStackedWidget, QFrame, QTextEdit, QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont

from 操作工具 import FPS视角转动, FPS_灵敏度
import suodi

import numpy as np
from PIL import ImageGrab
import sjz2


from pynput.keyboard import Key, Controller as KeyboardController, Listener
from pynput.mouse import Controller as MouseController, Button


ace = False
def 按键监听处理(key):
    """键盘按键监听回调：按下 F1 键触发退出"""
    global exit_flag
    try:
        # 检测是否按下了 F1 键
        if key == Key.f2:  # 注意：Key 来自 pynput.keyboard
            print("\n检测到 F2 键按下，准备退出程序...")
            exit_flag = True
            listener.stop()
            print("\n❗️检测到 F2 键按下，强制停止所有操作并退出❗️")
            os._exit(0)
    except AttributeError:
        # 某些特殊键（如 F1、Ctrl 等）会进入这里，但我们已经在上面用 key == Key.f1 处理了
        pass


# 启动键盘监听线程
listener = Listener(on_press=按键监听处理)
listener.start()

# ============================================================
# 全局配置（与 v1.08 一致）
# ============================================================
if getattr(sys, "frozen", None):
    basedir = sys._MEIPASS
else:
    basedir = os.path.join(sys.path[1], "")
path = basedir + "\\Resource\\"
if os.path.exists(path):
    os.chdir(path)
    DLL_PATH = path + "BEX-Coord-DLL.dll"
KEY = 20261234
APP_ID   = bytes([52,100,97,56,55,99,52,55,48,52,99,48,52,57,55,56,57,51,99,52,101,48,100,53,48,99,56,52,54,101,98,99])


CRYPT_ID =bytes([2,93,80,94,15,82,12,84,9,3,87,5,0,92,1,12,88,85,0,81,83,9,81,87,5,86,92,7,0,85,87,0])


移动超时秒 = 30
坐标误差 = 65
视角误差 = 1.0
视角校正次数 = 3

# 中控配置
BASE_URL = "http://114.132.81.95:6565"
DEFAULT_MACHINE = "1"

# 验证码识别 Key
验证码Key = "Kwfbmtu9"
验证码Key = ""

# ============================================================
#   开关：是否跳过中控账号申请，直接跑
#       True  = 不连中控，用下面的本地虚拟账号跳点
#       False = 正常走中控：申请账号→跑级→上报完成
# ============================================================
跳过中控申请 = False  # ← 改这里控制
LOCAL_ACCOUNT = "local_test"  # 跳过模式下的虚拟账号名
LOCAL_TARGET_LEVEL = 8  # 跳过模式下的目标等级
LOCAL_START_LEVEL = 0  # 跳过模式下的起始等级

# ============================================================
#   登录记忆：登录成功后将账号密码存到文件，
#   下次启动自动回填。
#       存放路径：脚本同目录下的 login_memo.json
#       格式：{"user": "...", "password": "..."}
#   注：明文存，不带加密（跳点项目本身也不是强安全场景）
# ============================================================
LOGIN_MEMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_memo.json")


def 加载登录记忆():
    """读取上一次登录成功的 user / password，读不到返回 ('', '')。"""
    try:
        if not os.path.exists(LOGIN_MEMO_FILE):
            return "", ""
        with open(LOGIN_MEMO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("user", "") or "", data.get("password", "") or ""
    except Exception as e:
        print(f"[登录记忆] 读取失败: {type(e).__name__}: {e}")
        return "", ""


def 保存登录记忆(user, password):
    """登录成功后调，写入 user / password。"""
    try:
        with open(LOGIN_MEMO_FILE, "w", encoding="utf-8") as f:
            json.dump({"user": user, "password": password}, f, ensure_ascii=False)
        print(f"[登录记忆] 已保存: {user}")
    except Exception as e:
        print(f"[登录记忆] 保存失败: {type(e).__name__}: {e}")


# 虚拟键码
VK_E = 0x45
VK_Z = 0x5A
VK_W = 0x57
VK_D = 0x44
VK_S = 0x53
VK_A = 0x41
VK_F = 0x46
VK_X = 0x58
VK_M = 0x4D
VK_R = 0x52
VK_ESCAPE = 0x1B
VK_DELETE = 0x2E
VK_BACK = 0x08
VK_TAB = 0x09
VK_SHIFT = 0xA0
VK_3 = 0x33
VK_5 = 0x35
VK_6 = 0x36
VK_SPACE = 0x20
VK_ALT = 0x12
VK_1 = 0x31

# ===== 移动前攀爬模板匹配（按 Shift 之前先识别，识别到就按 X 1 秒翻越）=====
攀爬识别模板 = "panpa.png"  # ← 模板图片名（与 .py 同目录）
攀爬识别范围 = (1218, 698, 1281, 749)  # ← 屏幕识别区域 (left, top, right, bottom)
攀爬识别阈值 = 0.8  # ← 相似度阈值
攀爬按X时长 = 1.0  # ← 按 X 持续秒数

# ===== DLL 读取容错：开启后 DLL 返回 False(无数据)时不更新坐标/视角，沿用上次有效值 =====
保留最新有效值 = True   # True=开启(无数据时沿用上次有效值)  False=原行为(DLL写什么用什么)

# ===== 动作2失败后视角扫描偏移量(度)——相对当前视角偏移 =====
动作2扫描_上偏移 = 13    # ← 往上偏移角度(度)
动作2扫描_下偏移 = 13    # ← 往下偏移角度(度)
动作2扫描_左偏移 = 20    # ← 往左偏移角度(度)
动作2扫描_右偏移 = 20    # ← 往右偏移角度(度)

# 鼠标事件
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


# ============================================================
# 输入操作工具函数（按键/鼠标全部封装）
# ============================================================
def 按键按下(vk码):
    扫描码 = ctypes.windll.user32.MapVirtualKeyW(vk码, 0)
    ctypes.windll.user32.keybd_event(vk码, 扫描码, 0, 0)


def 按键松开(vk码):
    扫描码 = ctypes.windll.user32.MapVirtualKeyW(vk码, 0)
    ctypes.windll.user32.keybd_event(vk码, 扫描码, 2, 0)


def 按键单击(vk码, 按下时长=0.05):
    """完整一次按键: 按下 → 等 → 松开"""
    按键按下(vk码)
    time.sleep(按下时长)
    按键松开(vk码)


def 组合键ALT_D():
    """按 Alt+D"""
    按键按下(VK_ALT)
    time.sleep(0.1)
    按键单击(VK_D)
    time.sleep(0.1)
    按键松开(VK_ALT)
    time.sleep(0.5)

def 鼠标左键按下():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)


def 鼠标左键松开():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def 鼠标左键单击(按下时长=0.05):
    鼠标左键按下()
    time.sleep(按下时长)
    鼠标左键松开()


def 鼠标右键按下():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)


def 鼠标右键松开():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def 鼠标移动到(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def 鼠标双击坐标(x, y, 间隔=0.08):
    鼠标移动到(x, y)
    time.sleep(0.05)
    鼠标左键单击()
    time.sleep(间隔)
    鼠标左键单击()


def 鼠标单击坐标(x, y):
    鼠标移动到(x, y)
    time.sleep(0.05)
    鼠标左键单击()


def 鼠标右键单击(按下时长=0.05):
    鼠标右键按下()
    time.sleep(按下时长)
    鼠标右键松开()


def 鼠标右击坐标(x, y):
    鼠标移动到(x, y)
    time.sleep(0.05)
    鼠标右键单击()


def 归一化角度(角度):
    """将角度归一化到 -180 ~ 180"""
    while 角度 > 180:
        角度 -= 360
    while 角度 < -180:
        角度 += 360
    return 角度


# ============================================================
# 自定义异常
# ============================================================
class 移动超时异常(Exception):
    pass


# ============================================================
# 通用工具函数（与 v1.08 一致）
# ============================================================
def 识别密码箱点击密码():
    time.sleep(2)
    按键单击(VK_F)
    time.sleep(4)
    time.sleep(25)
    鼠标双击坐标(1343, 219)
    time.sleep(1.5)
    鼠标双击坐标(1453, 215)
    time.sleep(1.5)
    按键单击(VK_ESCAPE)
    time.sleep(2)


def 设置鼠标():
    按键单击(VK_ESCAPE)
    time.sleep(2)
    鼠标单击坐标(964, 422)
    time.sleep(2)
    鼠标单击坐标(364, 110)
    time.sleep(2)
    鼠标单击坐标(777, 282)
    time.sleep(2)
    # 按 4 下删除键
    for _ in range(4):
        按键单击(VK_DELETE)
        time.sleep(0.2)
    # 再按一次 6 键
    按键单击(VK_6)
    time.sleep(0.2)
    鼠标单击坐标(468,158)
    time.sleep(2)
    鼠标单击坐标(564,566)
    time.sleep(2)
    按键单击(VK_5)
    time.sleep(2)
    按键单击(VK_ESCAPE)
    time.sleep(2)


def 开始卖东西():
    print("领取邮件")
    鼠标单击坐标(1750, 79)
    time.sleep(2)
    鼠标单击坐标(460, 100)
    time.sleep(2)
    鼠标单击坐标(154, 974)
    time.sleep(2)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)

    按键单击(VK_SPACE)
    time.sleep(1)
    鼠标单击坐标(389, 983)
    time.sleep(2)

    鼠标单击坐标(1177, 709)
    time.sleep(2)

    按键单击(VK_ESCAPE)
    time.sleep(2)
    print("去仓库卖")
    保证回到主页退出()
    仓库售卖操作()
    保证回到主页退出()
    print("领取邮件")
    鼠标单击坐标(1750, 79)
    time.sleep(2)
    鼠标单击坐标(460, 100)
    time.sleep(2)
    鼠标单击坐标(154, 974)
    time.sleep(2)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)

    按键单击(VK_SPACE)
    time.sleep(1)
    鼠标单击坐标(389, 983)
    time.sleep(2)

    鼠标单击坐标(1177, 709)
    time.sleep(2)

    按键单击(VK_ESCAPE)
    time.sleep(2)
    print("去仓库卖")
    保证回到主页退出()

    pass

def 开始卖东西2():
    print("先领取邮件")
    鼠标单击坐标(1750, 79)
    time.sleep(2)
    鼠标单击坐标(460, 100)
    time.sleep(2)
    鼠标单击坐标(154, 974)
    time.sleep(2)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)

    按键单击(VK_SPACE)
    time.sleep(1)
    鼠标单击坐标(389, 983)
    time.sleep(2)

    鼠标单击坐标(1177, 709)
    time.sleep(2)

    按键单击(VK_ESCAPE)
    time.sleep(2)
    print("去仓库卖")
    保证回到主页退出()
    仓库售卖操作()
    pass

def 保证回到主页退出():
    print("开始保证结束")
    点击坐标 = 模板匹配(1410, 755, 1872, 1032, "daba.png")
    if 点击坐标:

        pass
    else:
        按键单击(VK_ESCAPE)
        time.sleep(2)
    点击坐标 = 模板匹配(1410, 755, 1872, 1032, "wumubiao.png")
    if 点击坐标:

        pass
    else:
        按键单击(VK_ESCAPE)
        time.sleep(2)
    点击坐标 = 模板匹配(122,807,449,1086, "escjiemian.png")
    if 点击坐标:
        按键单击(VK_ESCAPE)
        time.sleep(2)
    点击坐标 = 模板匹配(122,807,449,1086, "escjiemian.png")
    if 点击坐标:
        按键单击(VK_ESCAPE)
        time.sleep(2)
    print("结束保证结束")
def 模板匹配(left, top, right, bottom, 模板图片路径, 阈值=0.8):
    try:
        import cv2
        模板 = cv2.imread(模板图片路径)
        if 模板 is None:
            return None
        截图 = ImageGrab.grab(bbox=(left, top, right, bottom))
        偏移X, 偏移Y = left, top
        屏幕 = cv2.cvtColor(np.array(截图), cv2.COLOR_RGB2BGR)
        th, tw = 模板.shape[:2]
        sh, sw = 屏幕.shape[:2]
        if th > sh or tw > sw:
            return None
        结果 = cv2.matchTemplate(屏幕, 模板, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(结果)
        if max_val >= 阈值:
            中心X = max_loc[0] + tw // 2 + 偏移X
            中心Y = max_loc[1] + th // 2 + 偏移Y

            return (中心X, 中心Y)
        else:

            return None
    except ImportError:

        return None
    except Exception as e:

        return None


def 仓库售卖操作():
    print("开始卖")
    鼠标单击坐标(326, 93)
    time.sleep(2)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    按键单击(VK_SPACE)
    time.sleep(1)
    鼠标单击坐标(1209, 926)
    time.sleep(1)

    次数 = 0

    卖枪=0
    while True:
        点击坐标 = 模板匹配(968, 668, 1300, 750, "fenghao.png")
        if 点击坐标:
            break
        # if 次数 > 15:
        #     按键单击(VK_ESCAPE)
        #     time.sleep(2)
        #     break
        print("===================开始卖")

        鼠标右击坐标(1260, 174)
        time.sleep(1)
        点击坐标 = 模板匹配(1177,117,1478,451, "chushou2.png")
        if 点击坐标:
            鼠标单击坐标(*点击坐标)
            time.sleep(1.5)
            次数 = 0
        else:
            次数 = 次数 + 1
            if 次数>3:
                break
            continue
        print("当前次数是",次数)
        
        
        if 卖枪 == 1:
            卖枪=0
            鼠标单击坐标(1421, 503)
            time.sleep(1)
            鼠标单击坐标(1209, 926)
            time.sleep(1)
            continue

        
        鼠标单击坐标(1414, 736)
        鼠标移动到(10, 10)
        time.sleep(3)
        
        点击坐标 = 模板匹配(1241, 437, 1565, 565, "chus.png")
        if 点击坐标:
            鼠标单击坐标(1421, 503)
            time.sleep(1)
            鼠标单击坐标(1209, 926)
            time.sleep(1)
            continue


        点击坐标 = 模板匹配(906,661,1072,744, "queren.png")
        if 点击坐标:
            鼠标单击坐标(1000, 700)
            time.sleep(2)
            鼠标单击坐标(1200, 770)
            time.sleep(2)

        # 鼠标单击坐标(512, 595)
        # time.sleep(1)

        # for sksdk in range(1, 5):
        #     鼠标单击坐标(1140, 670)
        #     time.sleep(0.2)



        点击坐标 = 模板匹配(1111,542,1551,633, "xuyaoxuanz.png",0.94)
        if 点击坐标:
            print("=================================需要点最低价")
            鼠标单击坐标(1434, 678)
            time.sleep(1)
            按键单击(VK_BACK)
            time.sleep(0.5)
            鼠标单击坐标(1700, 900)
            time.sleep(0.5)
            鼠标单击坐标(900, 600)
            time.sleep(1)

            鼠标单击坐标(1458, 591)
            time.sleep(0.5)

        else:
            卖枪 = 1

            按键单击(VK_ESCAPE)
            time.sleep(1.5)
            continue



        鼠标单击坐标(1362, 790)
        time.sleep(2)
        鼠标单击坐标(1209, 926)
        time.sleep(1)



def search_color_center(target_rgb, region=None, tolerance=1):
    """在指定区域搜索目标颜色，返回所有匹配点的中心坐标"""
    if region:
        screenshot = ImageGrab.grab(bbox=region)
        offset_x, offset_y = region[0], region[1]
    else:
        screenshot = ImageGrab.grab()
        offset_x, offset_y = 0, 0

    img_array = np.array(screenshot)
    r, g, b = target_rgb

    mask = (
            (np.abs(img_array[:, :, 0].astype(int) - r) <= tolerance) &
            (np.abs(img_array[:, :, 1].astype(int) - g) <= tolerance) &
            (np.abs(img_array[:, :, 2].astype(int) - b) <= tolerance)
    )

    matches = np.where(mask)
    if len(matches[0]) == 0:
        return None

    center_y = int(np.mean(matches[0])) + offset_y
    center_x = int(np.mean(matches[1])) + offset_x
    return center_x, center_y, len(matches[0])


def predict_image(image_path, question_type, key=None):
    with open(image_path, 'rb') as f:
        image_data = f.read()

    payload = {
        'base64Image': base64.b64encode(image_data).decode('utf-8'),
        'modelName': '普通模型',
        'keyCode': key if key else 验证码Key,
        'question': question_type,
        'system': ''
    }

    response = requests.post('http://gpu1.xinyuocr.xyz:8889/api/qrcode/predict', json=payload)

    return response.json()


def 识别物资点击():
    ss=识别物资点击2()
    if ss==0:
        pass
    else:
        return 1
    # # 金色物资
    # result = search_color_center(target_rgb=(59, 48, 37), region=(1254, 105, 1739, 940), tolerance=1)
    # if result:
    #     x, y, count = result
    #     print(f"金色物资中心坐标: ({x}, {y})  匹配像素数: {count}")
    #     if count >= 6:
    #         鼠标双击坐标(x, y)
    #         time.sleep(1)
    #         return
    # # 深紫色物资
    # result = search_color_center(target_rgb=(51, 51, 60), region=(1254, 105, 1739, 940), tolerance=2)
    # if result:
    #     x, y, count = result
    #     print(f"深紫色物资中心坐标: ({x}, {y})  匹配像素数: {count}")
    #     if count >= 6:
    #         鼠标双击坐标(x, y)
    #         time.sleep(1)
    #         return
    # # 深紫色物资
    # result = search_color_center(target_rgb=(41, 39, 50), region=(1254, 105, 1739, 940), tolerance=2)
    # if result:
    #     x, y, count = result
    #     print(f"深紫色2物资中心坐标: ({x}, {y})  匹配像素数: {count}")
    #     if count >= 6:
    #         鼠标双击坐标(x, y)
    #         time.sleep(1)
    #         return
    # # 藏青色物资
    # for _轮 in range(4):
    result = search_color_center(target_rgb=(33, 44, 54), region=(1254, 105, 1739, 940), tolerance=1)
    if result:
        x, y, count = result
        print(f"藏青色物资中心坐标: ({x}, {y})  匹配像素数: {count}")
        if count >= 10:
            鼠标双击坐标(x, y)
            time.sleep(1)
            return
    print("未找到任何物资")
    return 0


def 自动登录账号密码(账号, 密码):
    sjz2.switch_and_login(账号, 密码)
    pass
def capture_screenshot(region, save_path):
    """截图指定范围并保存

    参数:
        region: 截图范围 (left, top, right, bottom)
        save_path: 保存路径
    """
    try:
        from PIL import ImageGrab

        # 在指定范围内截图
        left, top, right, bottom = region
        screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))

        # 保存截图
        screenshot.save(save_path)
        # self.log_signal.emit("    截图已保存至：" + save_path + "，区域：( " + str(left) + ", " + str(top) + ", " + str(right) + ", " + str(bottom) + " )")
    except Exception as e:
        print("    截图保存出错：" + str(e))
def 动作3_按F():
        time.sleep(0.7)
        print("开始")
        点击坐标 = 模板匹配(1100, 559, 1182, 626, "kaimen.png")
        if 点击坐标:
            # 测试没问题,  一个月十块钱 不限制设备
            def image_to_base64(img_path):
                """读取本地图片并转成 base64 字符串"""
                with open(img_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')

            def ocr_by_base64(img_path, mode='mixed', scale=1, padding=0, detail=0):
                """
                通过 base64 上传图片到 RapidOCR 服务端识别。
                :param img_path: 本地图片路径
                :param mode:     识别模式: digit / english / chinese / mixed
                :param scale:    整数倍放大，默认 1；小图识别不准时可试 2 或 3
                :param padding:  四周加白边像素数，默认 0；字符贴边漏识别时试 8~20
                :param detail:   0=只返回文本字符串；1=返回每块 box+text+score
                """
                SERVER_URL = "http://106.52.36.160:10828/ocr"
                payload = {
                    "image_base64": image_to_base64(img_path),
                    "mode": mode,
                    "scale": scale,
                    "padding": padding,
                    "detail": detail,
                }
                t0 = time.time()
                resp = requests.post(SERVER_URL, json=payload, timeout=60)
                print(resp)
                cost_ms = (time.time() - t0) * 1000
                data = resp.json()

                if data.get("code") == 0:
                    print("[识别成功][mode=%s][scale=%d][pad=%d][detail=%d][耗时=%.1fms]"
                          % (data.get("mode", mode), scale, padding, detail, cost_ms))
                    result = data["result"]
                    if isinstance(result, list):
                        for item in result:
                            print("  ", item)
                    else:

                        print("  =>", repr(result))
                else:
                    print("[识别失败]", data.get("msg"))
                clean_text = result.replace("\n", "")
                print(clean_text)
                return clean_text

            def img_to_base64(img_path):
                with open(img_path, 'rb') as read:
                    b64 = base64.b64encode(read.read())
                return b64

            # 替换 URL=http://116.204.132.93:8089/
            url = 'http://116.204.132.93:8089//api/tr-run/'

            # 截图保存指定范围 (1513,834,1693,869) 为 AAA.png
            capture_screenshot((1152,575,1195,612), 'AAA.png')
            time.sleep(0.2)
            验证模式 = 3
            if 验证模式 == 3:
                # ========== 修改为你要识别的图片路径 ==========
                test_image = 'AAA.png'
                # ==============================================

                # mode 可选: digit(只数字) / english(只英文) / chinese(只中文) / mixed(混合)
                test_mode = 'mixed'

                # === 可选预处理参数（一般不用动；图很小或字符贴边时再调） ===
                test_scale = 1  # 图片整数倍放大，小图建议 2~3
                test_padding = 1  # 四周加白边像素数，字符贴边漏识别时建议 10~20

                # 0 = 只返回文本字符串；1 = 返回每块 box+text+score 详细信息
                test_detail = 0

                # print("=" * 50)
                # print("【RapidOCR base64 识别】mode=%s scale=%d padding=%d detail=%d"
                #       % (test_mode, test_scale, test_padding, test_detail))
                # print("=" * 50)
                sdads = ocr_by_base64(test_image,
                                      mode=test_mode,
                                      scale=test_scale,
                                      padding=test_padding,
                                      detail=test_detail)
                print(len(sdads))
                if "开" in sdads:
                    按键单击(VK_F,2)
                    time.sleep(2)
                if "长" in sdads:
                    按键单击(VK_F,2)
                    time.sleep(2)



def 识别物资点击2(次数=0):




    if 次数<2:
        for i in range(2):
            result = search_color_center(target_rgb=(24, 36, 31), region=(1254, 105, 1739, 940), tolerance=1)
            if result:
                x, y, count = result
                print(f"中心坐标: ({x}, {y})  匹配像素数: {count}")
                鼠标双击坐标(x, y)
                time.sleep(0.5)
    # 金色物资
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "hongse.png",0.93)
    if 点击坐标:
        print("红色物资")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "jinse4.png",0.97)
    if 点击坐标:
        print("金色物4")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "jinse3.png",0.92)
    if 点击坐标:
        print("金色物33")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "jinse6.png",0.98)
    if 点击坐标:
        print("金色物资6")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "jinse5.png",0.96)
    if 点击坐标:
        print("金色物资5")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "jinse.png",0.95)
    if 点击坐标:
        print("金色物资")
        鼠标双击坐标(*点击坐标)
        return 1
    # 点击坐标 = 模板匹配(1254, 105, 1739, 940, "jinse2.png",0.98)
    # if 点击坐标:
    #     print("金色物资2")
    #     鼠标双击坐标(*点击坐标)
    #     return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "zise3.png",0.98)
    if 点击坐标:
        print("紫色物资3")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "zise2.png",0.95)
    if 点击坐标:
        print("紫色物资2")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "zise.png",0.95)
    if 点击坐标:
        print("紫色物资")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "zise4.png",0.98)
    if 点击坐标:
        print("紫色物资4")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "lanse.png",0.98)
    if 点击坐标:
        print("蓝色物资1")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "lanse2.png",0.95)
    if 点击坐标:
        print("蓝色物资2")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "lanse3.png",0.95)
    if 点击坐标:
        print("蓝色物资3")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "lanse4.png",0.95)
    if 点击坐标:
        print("蓝色物资4")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "lanse5.png",0.95)
    if 点击坐标:
        print("蓝色物资5")
        鼠标双击坐标(*点击坐标)
        return 1
    点击坐标 = 模板匹配(1254, 105, 1739, 940, "lanse6.png",0.95)
    if 点击坐标:
        print("蓝色物资6")
        鼠标双击坐标(*点击坐标)
        return 1
    print("未找到任何物资")
    return 0


import re


def parse_amount_to_number(amount_str):
    """
    将带有特殊符号、空格和单位的字符串转换为正确的金额数字。
    例如: '?3,283K' -> 3283000
    """
    if not isinstance(amount_str, str):
        return None

    # 1. 统一转大写并去除所有空格
    cleaned_str = amount_str.upper().replace(" ", "")

    # 2. 用正则提取：可选的负号 + 数字(含逗号和小数点) + 可选的单位(K/M/B)
    # 匹配逻辑：开头可能有非数字字符，然后捕获 数字部分 和 单位部分
    match = re.search(r'[-+]?[\d,]+\.?\d*\s*([KMB])?', cleaned_str)

    if not match:
        return None  # 如果完全匹配不到数字，返回 None

    # 3. 分离数字和单位
    # 重新从清理后的字符串中提取纯数字部分（保留负号和逗号、小数点）
    num_match = re.search(r'([-+]?[\d,]+\.?\d*)', cleaned_str)
    number_part = num_match.group(1).replace(",", "")  # 去掉千分位逗号

    unit_match = re.search(r'([KMB])', cleaned_str)
    unit = unit_match.group(1) if unit_match else None

    try:
        base_value = float(number_part)
    except ValueError:
        return None

    # 4. 根据单位进行倍率换算
    multiplier = 1
    if unit == 'K':
        multiplier = 1_000  # 千
    elif unit == 'M':
        multiplier = 1_000_000  # 百万
    elif unit == 'B':
        multiplier = 1_000_000_000  # 十亿

    result = base_value * multiplier

    # 5. 如果结果是整数，就返回 int，否则返回 float
    return int(result) if result.is_integer() else result


# # 金色物资
# 点击坐标 = 模板匹配(1220,137,1587,577, "lvse.png", 0.98)
# if 点击坐标:
#     print("绿色物资")
#     鼠标双击坐标(*点击坐标)
#     time.sleep(0.5)
# exit()

# 新手模式拿完东西 第一把啊就  先吃药 然后出来领取任务 然后就可以 继续买药继续完成任务  后续正常开局正常杀人  重复刷图跑刀 然后有亮了再去完成任务 然后看到任务能直接做的就直接点 不能的就退出去刷图


#
# 识别物资点击2()
# exit()



# ============================================================
# 自动跑点核心类（完整复制自 v1.08）
# ============================================================
class 自动跑点:
    def __init__(self, 日志回调=print):
        self.日志 = 日志回调
        self.dll = None
        self.已初始化 = False
        self.停止标志 = False
        self.三级清包=0
        self.task_level2_executed = False
        # ------------------------------------------------------------
        # 服务器下发的目标值（来自 /fetch_account 回包）
        # ------------------------------------------------------------
        self.目标等级 = ""
        self.目标金币 = ""
        self.目标key = ""
        # ------------------------------------------------------------
        # 游戏账号（不是中控账号）
        #   中控账号 = 用户在 UI 填的登录中控的账号（在 中控客户端.user）
        #     只用来心跳 / 设备状态上报。
        #   游戏账号 = 中控账号名下上传的账号库被 /fetch_account 撑出来的一条。
        #     主线程实际要跑的游戏里那个账号就是它，
        #     跑完后 /update_account 上报的也是这个账号。
        # ------------------------------------------------------------
        self.游戏账号 = None
        self.游戏密码 = None
        self.当前等级 = None

        # ------------------------------------------------------------
        # 跑一局过程中的状态计数、最终要回执给服务器的
        # （与 test_fetch_account.py 的 FINAL_LEVEL / FINAL_COINS 一一对应）
        # ------------------------------------------------------------
        self.最终等级 = 0
        self.最终金币 = 0
        self.px = ctypes.c_float()
        self.py = ctypes.c_float()
        self.pz = ctypes.c_float()
        self.pitch = ctypes.c_float()
        self.yaw = ctypes.c_float()

    # ===== DLL 读取包装(带容错) =====
    def 读坐标(self):
        if 保留最新有效值:
            _x, _y, _z = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
            ok = self.dll.BEX_GetPlayerPos(_x, _y, _z)
            if ok:
                self.px.value = _x.value
                self.py.value = _y.value
                self.pz.value = _z.value
            else:
                self.日志(f"[DLL] 读坐标无数据，沿用上次值 ({self.px.value:.1f},{self.py.value:.1f},{self.pz.value:.1f})")
            return ok
        else:
            return self.dll.BEX_GetPlayerPos(self.px, self.py, self.pz)

    def 读视角(self):
        if 保留最新有效值:
            _p, _y = ctypes.c_float(), ctypes.c_float()
            ok = self.dll.BEX_GetRotation(_p, _y)
            if ok:
                self.pitch.value = _p.value
                self.yaw.value = _y.value
            else:
                self.日志(f"[DLL] 读视角无数据，沿用上次值 (pitch={self.pitch.value:.2f},yaw={self.yaw.value:.2f})")
            return ok
        else:
            return self.dll.BEX_GetRotation(self.pitch, self.yaw)

    def move_game_window(self):
        """循环查找游戏窗口句柄，找不到 5 秒后重试，无限循环直到找到。
        找到后移动窗口到 (0,0)，再等待 10 秒后返回。
        任何时刻 self.停止标志=True 都会中断返回 False。
        """
        self.日志("========== 等待游戏窗口 ==========")
        第几次 = 0
        hwnd = 0
        while True:
            if self.停止标志:
                self.日志("[等待窗口] 用户中断")
                return False
            第几次 += 1
            try:
                hwnd = ctypes.windll.user32.FindWindowW("UnrealWindow", None)
                if not hwnd:
                    hwnd = ctypes.windll.user32.FindWindowW(None, "三角洲行动")
            except Exception as e:
                self.日志(f"[等待窗口] 第 {第几次} 次查找异常: {type(e).__name__}: {e}")
                hwnd = 0
            if hwnd:
                self.日志(f"[等待窗口] 第 {第几次} 次查找成功 hwnd={hwnd}")
                break
            self.日志(f"[等待窗口] 第 {第几次} 次未找到，5 秒后重试...")
            for _ in range(5):
                if self.停止标志:
                    self.日志("[等待窗口] 用户中断")
                    return False
                time.sleep(1)

        # 移动窗口到左上角
        try:
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0004)
            self.日志("[移动窗口] 成功")
        except Exception as e:
            self.日志(f"[移动窗口] 失败: {type(e).__name__}: {e}")

        # 激活窗口：还原最小化 + 提到顶 + 抢焦点
        try:
            SW_RESTORE = 9
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            ctypes.windll.user32.BringWindowToTop(hwnd)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            self.日志("[激活窗口] 已还原 + 置顶 + 抢焦点")
        except Exception as e:
            self.日志(f"[激活窗口] 失败: {type(e).__name__}: {e}")

        self.日志("[等待窗口] 移动完成，等待 10 秒后继续")
        for _ in range(5):
            if self.停止标志:
                self.日志("[等待窗口] 用户中断")
                return False
            time.sleep(1)
        self.日志("========== 游戏窗口就绪 ==========")
        return True

    def 关闭游戏窗口(self):
        """查找三角洲窗口并发送关闭消息"""
        self.日志("========== 关闭游戏窗口 ==========")
        try:
            hwnd = ctypes.windll.user32.FindWindowW("UnrealWindow", None)
            if not hwnd:
                hwnd = ctypes.windll.user32.FindWindowW(None, "三角洲行动")
            if hwnd:
                WM_CLOSE = 0x0010
                ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                self.日志(f"[关闭窗口] 已发送关闭消息 hwnd={hwnd}")
                return True
            else:
                self.日志("[关闭窗口] 未找到游戏窗口")
                return False
        except Exception as e:
            self.日志(f"[关闭窗口] 异常: {type(e).__name__}: {e}")
            return False

    # ----- DLL 生命周期 -----
    def 初始化(self):
        # 声明全局变量
        global DLL_PATH

        # ========== 把下面这段路径代码粘贴在这里 ==========
        import sys
        # 修正路径逻辑
        if getattr(sys, "frozen", None):
            basedir = sys._MEIPASS
        else:
            # 当前脚本所在文件夹
            basedir = os.path.dirname(os.path.abspath(__file__))
        # 逐层拼接目录
        res_dir = os.path.join(basedir, "Resource")
        DLL_PATH = os.path.join(res_dir, "BEX-Coord-DLL.dll")
        # ================================================

        if self.已初始化:
            self.日志("[*] DLL 已初始化，跳过")
            return True

        if not os.path.exists(DLL_PATH):
            self.日志(f"[ERROR] DLL 不存在: {DLL_PATH}")
            return False

        self.日志("========== 开始加载驱动==========")
        self.dll = ctypes.CDLL(DLL_PATH)

        self.dll.BEX_Init.restype = ctypes.c_int
        self.dll.BEX_Init.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p]
        self.dll.BEX_GetPlayerPos.restype = ctypes.c_bool
        self.dll.BEX_GetPlayerPos.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
        self.dll.BEX_GetCameraPos.restype = ctypes.c_bool
        self.dll.BEX_GetCameraPos.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
        self.dll.BEX_GetRotation.restype = ctypes.c_bool
        self.dll.BEX_GetRotation.argtypes = [ctypes.POINTER(ctypes.c_float)] * 2
        self.dll.BEX_Shutdown.restype = None
        self.dll.BEX_Shutdown.argtypes = []

        ERROR_MSG = {
            -1: "wrong key",
            -2: "找不到游戏窗口 (UnrealWindow) - DeltaForce 在跑吗?",
            -3: "get PID failed",
            -4: "Drv_Regist failed (检查 AppId/CryptAppId)",
            -5: "Drv_InitByVersion failed",
            -6: "驱动未安装",
            -7: "ImageBase = 0 (游戏刚启动，请重试)",
        }
        self.日志("[*] 正在初始化驱动...")
        code = self.dll.BEX_Init(KEY, APP_ID, CRYPT_ID)
        if code != 1:
            msg = ERROR_MSG.get(code, f"unknown code {code}")
            self.日志(f"[ERROR] 初始化失败 [{code}]: {msg}")
            # ========== 关键：释放脏 DLL，确保下次重试拿到干净实例 ==========
            self.日志("========== 清理脏 DLL 句柄 ==========")
            try:
                self.dll.BEX_Shutdown()
                self.日志("[清理] BEX_Shutdown 已调用")
            except Exception as e:
                self.日志(f"[清理] BEX_Shutdown 异常(忽略): {type(e).__name__}: {e}")
            try:
                _h = self.dll._handle
                ctypes.windll.kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
                ctypes.windll.kernel32.FreeLibrary.restype = ctypes.c_int
                _ok = ctypes.windll.kernel32.FreeLibrary(_h)
                self.日志(f"[清理] FreeLibrary 已释放 DLL 句柄(handle=0x{_h:X}, ret={_ok})")
            except Exception as e:
                self.日志(f"[清理] FreeLibrary 异常(忽略): {type(e).__name__}: {e}")
            self.dll = None
            self.已初始化 = False
            self.日志("========== 脏 DLL 已清理，下次重试将重新加载 ==========")
            return False

        self.日志("[OK] 驱动已就绪")
        self.日志("========== DLL 加载完成 ==========")
        self.已初始化 = True
        return True

    def 关闭(self):
        if self.dll and self.已初始化:
            self.dll.BEX_Shutdown()
            self.已初始化 = False
            self.日志("[*] DLL 已关闭")

    # ----- 主线程：带重试初始化 + 路线执行 -----
    def 主线程(self, 最大重试次数=5, 重试间隔秒=5,
               游戏账号=None, 游戏密码=None,
               起始等级=0, 起始金币=0, 不匹配队友=False, 目标key=None):
        # 记录服务器下发的目标值
        self.目标等级 = int(起始等级) if 起始等级 else 0
        self.目标金币 = int(起始金币) if 起始金币 else 0
        self.目标key = 目标key
        print("目标金币是", self.目标金币)
        print("目标等级是", self.目标等级)
        print("目标key是", self.目标key)
        if self.目标金币 > 1:
            print("目标金币正常")
        if self.目标等级 > 1:
            print("目标等级正常")

        # 启动先查找游戏窗口并移动（无限重试，成功后等 10 秒）
        if not self.move_game_window():
            self.日志("[主线程] 等待游戏窗口被中断，主线程退出")
            return False

        self.停止标志 = False
        # 记住本局要跑的游戏账号，合入 self 供后续跳点代码使用
        if 游戏账号 is not None:
            self.游戏账号 = 游戏账号
        if 游戏密码 is not None:
            self.游戏密码 = 游戏密码
        # 初始值先填进最终值，跑完不更新就原样上报
        self.最终等级 = int(起始等级)
        self.最终金币 = int(起始金币)
        self.日志("========== 主线程启动 ==========")
        self.不匹配队友 = 不匹配队友
        self.日志(f"[主线程] 不匹配队友 = {self.不匹配队友}")
        if self.游戏账号:
            self.日志(f"[主线程] 本局游戏账号: {self.游戏账号}")
            self.日志(f"[主线程] 本局游戏密码: {self.游戏密码}")
        else:
            self.日志("[主线程] 本局没有传入游戏账号（测试或本地模式）")
        self.日志(f"[主线程] 起始等级={self.最终等级}  起始金币={self.最终金币}")
        self.日志(f"初始化策略: 最多重试 {最大重试次数} 次，间隔 {重试间隔秒} 秒")
        第几次 =0
        初始化成功 = False
        if not self.已初始化:

            while True:
                第几次+=1
                if self.停止标志:
                    self.日志("[*] 初始化阶段被用户中断")
                    return False
                self.日志(f"\n[初始化] 第 {第几次}/{最大重试次数} 次尝试...")
                if self.初始化():
                    self.日志(f"[初始化] 第 {第几次} 次成功 ✓")
                    初始化成功 = True
                    break
                self.日志(f"[初始化] 第 {第几次} 次失败 ✗")
                # if 第几次 < 最大重试次数:
                self.日志(f"[初始化] 等待 {重试间隔秒} 秒后重试...")
                等待终点 = time.time() + 重试间隔秒
                while time.time() < 等待终点:
                    if self.停止标志:
                        return False
                time.sleep(0.2)

            if not 初始化成功:
                self.日志(f"\n========== 初始化 {最大重试次数} 次全部失败 ==========")
                self._弹窗错误(
                    f"驱动注入失败\n\n已重试 {最大重试次数} 次仍未成功\n\n请检查：\n"
                    "1. 三角洲行动 是否已启动\n"
                    "2. 驱动是否已安装\n"
                    "3. key 是否正确",
                    标题="驱动注入失败"
                )
                return False

        self.日志("\n[主线程] 初始化就绪，开始调用 执行路线文件")

        是否完成 = "已完成"
        while True:


            print("检测当前状态是否是新号")
            新号 = 0
            点击坐标 = self.模板匹配(792, 827, 1133, 1015, "queren.png")
            if 点击坐标:
                self.日志(f"[主线程] 识别到目标，点击 {点击坐标}")
                鼠标单击坐标(1260, 533)
                time.sleep(2.5)
                鼠标单击坐标(1113, 535)
                time.sleep(0.5)
                按键单击(VK_BACK)
                随机字母 = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                按键单击(ord(随机字母))
                time.sleep(2.5)
                鼠标单击坐标(*点击坐标)
                鼠标单击坐标(1260, 533)
                time.sleep(2.5)
                time.sleep(2.5)
                新号 = 1
            else:
                self.日志("[主线程] 未识别到目标，跳过点击")

            if 新号 == 1:
                while True:
                    点击坐标 = self.模板匹配(792, 827, 1133, 1015, "queren.png")
                    if 点击坐标:
                        鼠标单击坐标(1260, 533)
                        time.sleep(2.5)
                        鼠标单击坐标(1113, 535)
                        time.sleep(0.5)
                        按键单击(VK_BACK)
                        随机字母 = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                        按键单击(ord(随机字母))
                        time.sleep(2.5)
                        鼠标单击坐标(*点击坐标)
                        鼠标单击坐标(1260, 533)
                        time.sleep(5)
                    else:
                        break

            if 新号 == 1:
                self.新号模式()
            点击坐标 = self.模板匹配(0, 432, 1675, 893, "kaitou1.png")

            time.sleep(5)
            if 点击坐标:
                鼠标单击坐标(461, 585)
                time.sleep(2.5)
                鼠标单击坐标(939, 689)
                print("--------------------------------------------------------------------------------")
                time.sleep(2.5)
            点击坐标 = self.模板匹配(0, 432, 1675, 893, "kaitou2.png")
            if 点击坐标:
                鼠标单击坐标(461, 585)
                time.sleep(2.5)

            新号 = self.返回首页()
            if 新号 == 2:
                新号 = 1
                点击坐标 = self.模板匹配(792, 827, 1133, 1015, "queren.png")
                if 点击坐标:
                    self.日志(f"[主线程] 识别到目标，点击 {点击坐标}")
                    鼠标单击坐标(1260, 533)
                    time.sleep(2.5)
                    鼠标单击坐标(1113, 535)
                    time.sleep(0.5)
                    按键单击(VK_BACK)
                    随机字母 = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                    按键单击(ord(随机字母))
                    time.sleep(2.5)
                    鼠标单击坐标(*点击坐标)
                    鼠标单击坐标(1260, 533)
                    time.sleep(2.5)
                    time.sleep(2.5)
                    新号 = 1
                else:
                    self.日志("[主线程] 未识别到目标，跳过点击")

                if 新号 == 1:
                    while True:
                        点击坐标 = self.模板匹配(792, 827, 1133, 1015, "queren.png")
                        if 点击坐标:
                            鼠标单击坐标(1260, 533)
                            time.sleep(2.5)
                            鼠标单击坐标(1113, 535)
                            time.sleep(0.5)
                            按键单击(VK_BACK)
                            随机字母 = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                            按键单击(ord(随机字母))
                            time.sleep(2.5)
                            鼠标单击坐标(*点击坐标)
                            鼠标单击坐标(1260, 533)
                            time.sleep(5)
                        else:
                            break

                if 新号 == 1:
                    self.新号模式()

                点击坐标 = self.模板匹配(0, 432, 1675, 893, "kaitou1.png")
                if 点击坐标:
                    鼠标单击坐标(461, 585)
                    time.sleep(2.5)
                点击坐标 = self.模板匹配(0, 432, 1675, 893, "kaitou2.png")
                if 点击坐标:
                    鼠标单击坐标(461, 585)
                    time.sleep(2.5)
            # 新号=1
            if 新号==1:
                卖次数=0
                等级=1
            else:
                卖次数=10
                等级=3

            self.三级清包 = 0
            检查等级=1
            while True:
                点击坐标 = self.模板匹配(268, 468, 1500, 950, "fenghao.png")
                if 点击坐标:
                    是否完成 = "已封号"
                    break

                print("持续主线程一直重复跑刀到等级结束")

                # 点击坐标 = self.模板匹配(1799, 1062, 1877, 1126, "3.png")
                # if 点击坐标 and 新号 == 0:
                #     self.三级清包 = 1
                #     pass
                # 点击坐标 = self.模板匹配(1799, 1062, 1877, 1126, "2.png")
                # if 点击坐标:
                #     self.三级清包 = 0

                try:
                    if self.三级清包 ==1:
                        if 卖次数>2:
                            if 等级 > 2:
                                鼠标单击坐标(1800, 1065)
                                time.sleep(2)
                                等级 = self.识别文字()
                                等级 = int(等级)
                                检查等级 = 0
                                print("等级是",等级)
                                按键单击(VK_ESCAPE);
                                time.sleep(2)
                                金额 = self.识别文字2()

                                金额=parse_amount_to_number(金额)
                                金额 = int(金额)
                                print("金额是",金额)
                                if 金额 > self.目标金币 and 等级 >= self.目标等级:
                                    print("金额达标 等级达标")
                                    break
                                time.sleep(1)
                                if 等级 > 2:
                                    开始卖东西()
                                    卖次数=0
                except Exception as e:
                    print("==========================================================识别异常")
                    保证回到主页退出()

                点击坐标 = self.模板匹配(790,333,1268,816, "dituye.png")
                if 点击坐标:
                    按键单击(VK_ESCAPE, 1)
                    time.sleep(2)
                点击坐标 = self.模板匹配(1410, 755, 1872, 1032, "wumubiao.png")
                if 点击坐标:
                    鼠标单击坐标(1650, 996);
                    time.sleep(4.5)
                    鼠标单击坐标(824, 296);
                    time.sleep(1.5)
                    鼠标单击坐标(1647, 662);
                    time.sleep(3.5)
                    按键单击(VK_SPACE);
                    time.sleep(2)
                    鼠标单击坐标(1719, 987);
                    time.sleep(1.5)
                    鼠标单击坐标(998, 735);
                    time.sleep(1.5)
                点击坐标 = self.模板匹配(896, 986, 978, 1046, "4.png")
                if 点击坐标:
                    按键单击(VK_TAB)
                    time.sleep(2)
                点击坐标 = self.模板匹配(1184, 519, 1891, 1079, "daoju.png")
                if 点击坐标:
                    print("=======================================3级引导流程卖金色设备")
                    鼠标单击坐标(*点击坐标)
                    time.sleep(2)
                    # self.三级清包=1
                    点击坐标 = self.模板匹配(884, 519, 1891, 1079, "chushou.png")
                    if 点击坐标:
                        鼠标单击坐标(*点击坐标)
                        time.sleep(2)
                        鼠标单击坐标(1401, 731)
                        time.sleep(2)
                        鼠标单击坐标(1374, 781)
                        time.sleep(2)
                        按键单击(VK_ESCAPE);
                        time.sleep(2)
                点击坐标 = self.模板匹配(1225, 895, 1318, 973, "zhengli.png")
                if 点击坐标:
                    鼠标单击坐标(1224, 932)
                    time.sleep(2.5)
                    按键单击(VK_ESCAPE, 1)
                    time.sleep(2)
                跑图 = 0

                保证回到主页退出()
                try:
                    if self.三级清包==0:
                        鼠标单击坐标(1800, 1065)
                        time.sleep(2)
                        等级=self.识别文字()
                        等级=int(等级)
                        print("等级是", 等级)
                        按键单击(VK_ESCAPE)
                        time.sleep(2)
                        if 等级==1:
                            新号 =1
                        检查等级 =0
                        if 等级>=3:
                            self.日志("==========已经到达3级 开始清包==========")
                            print("==========================================================开启仓库售卖")
                            self.三级清包 = 1
                            卖次数 = 0
                            开始卖东西()
                            卖次数 = 0
                            金额 = self.识别文字2()
                            print("金额是",金额)
                            金额=parse_amount_to_number(金额)
                            金额 = int(金额)
                            print("金额是",金额)
                            if 金额 > self.目标金币 and 等级 >= self.目标等级:
                                print("金额达标 等级达标")
                except Exception as e:
                    print("==========================================================识别异常")
                    保证回到主页退出()
                检查等级2 = 1
                if 检查等级2==1:
                    print("=========================================================继续检查等级")
                    try:
                        鼠标单击坐标(1800, 1065)
                        time.sleep(2)
                        等级 = self.识别文字()
                        等级 = int(等级)
                        print("等级是", 等级)
                        按键单击(VK_ESCAPE);
                        time.sleep(2)
                        if 等级 == 1:
                            新号 = 1
                        if 等级 == 3:
                            self.日志("==========已经到达3级 开始清包==========")
                            print("==========================================================开启仓库售卖")
                            self.三级清包 = 1
                            卖次数 = 0
                            开始卖东西()
                            卖次数 = 0
                            金额 = self.识别文字2()
                            print("金额是", 金额)
                            金额 = parse_amount_to_number(金额)
                            print("金额是", 金额)
                            if 金额 > self.目标金币 and 等级 >= self.目标等级:
                                print("金额达标 等级达标")
                        if 等级 == 6:
                            self.日志("==========已经到达6级 开始清包==========")
                            print("==========================================================开启仓库售卖")
                            卖次数 = 0
                            开始卖东西()
                            卖次数 = 0
                            金额 = self.识别文字2()
                            print("金额是", 金额)
                            金额 = parse_amount_to_number(金额)
                            金额 = int(金额)
                            print("金额是", 金额)
                            if 金额 > self.目标金币 and 等级 >= self.目标等级:
                                print("jinger",金额)
                                print("dengji",等级)
                                print("金额达标 等级达标")
                                break
                    except Exception as e:
                        print("==========================================================识别异常")
                        保证回到主页退出()

                if 新号 == 0:
                    if 等级 > 1:
                        self.启动前配置装备购买()
                点击坐标 = self.模板匹配(1410, 755, 1872, 1032, "daba.png")
                if 点击坐标:
                    print("============================地图是巴进入地图")
                    if self.不匹配队友:
                        点击坐标 = self.模板匹配(1643, 697, 1686, 737, "piduiyou.png")
                        if 点击坐标:
                            print("============================关闭队友匹配")
                            鼠标单击坐标(1663, 718)
                            time.sleep(1.5)
                    global rty

                    self.购买跨越生命线01任务药品()

                    鼠标单击坐标(589, 86)  # 点击部门
                    time.sleep(2)
                    按键单击(VK_SPACE)
                    time.sleep(0.5)
                    鼠标单击坐标(283, 539)  # 点击震荡危情
                    time.sleep(2)


                    点击坐标 = self.模板匹配(1536,948,1845,1018, "lingqu.bmp")
                    if 点击坐标:
                        鼠标单击坐标(1536,948)
                        time.sleep(2) 

                    点击坐标 = self.模板匹配(1537,946,1845,1016, "jiequ.bmp")
                    if 点击坐标:
                        鼠标单击坐标(1536, 948)
                        time.sleep(2)

                    鼠标单击坐标(328, 110)  # 点击跨越生命线
                    time.sleep(2)

                    点击坐标 = self.模板匹配(1536, 948, 1845, 1018, "lingqu.bmp")
                    if 点击坐标:
                        鼠标单击坐标(1536, 948)
                        time.sleep(2)

                    点击坐标 = self.模板匹配(1537, 946, 1845, 1016, "jiequ.bmp")
                    if 点击坐标:
                        鼠标单击坐标(1536, 948)
                        time.sleep(2)

                    self.跨越生命线01领取()
                    self.任务_跨越生命线02()
                    按键单击(VK_ESCAPE)
                    time.sleep(0.5)
                    按键单击(VK_ESCAPE)
                    time.sleep(0.5)
                    按键单击(VK_ESCAPE)
                    time.sleep(0.5)
                    按键单击(VK_ESCAPE)  # 回到主页
                    time.sleep(0.5)
                        # =====================================================
                    # self.新手配置装备()
                    鼠标单击坐标(1778, 999)
                    print("============================进入地图123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123123")
                    time.sleep(10.5)
                    跑图 = 1
                    需要再次按下=0
                    for dsf in range(1,5):
                        点击坐标 = self.模板匹配(700,268,1336,702, "yaoyanz.png")
                        if 点击坐标:
                            # 使用示例
                            需要再次按下 = 1
                            self.capture_screenshot((811,406,1114,699), 'AAA.png')
                            time.sleep(0.2)
                            image_path = 'AAA.png'
                            question_type = '回答图中问题'  # 或 '识别图中文本' // 仅支持英文和数字' 或 '回答图中问题'
                            result = predict_image(image_path, question_type, self.目标key)
                            print(result)
                            value = result['msg']
                            print(value)  # 输出: 6
                            # 2. 使用 split(',') 按逗号进行分割，得到数字字符串列表
                            numbers = value.split(',')

                            # 3. 逐个输出（循环遍历列表）
                            for num in numbers:
                                print(num)
                                value=int(num)

                                if value == 1:
                                    鼠标单击坐标(863,532)
                                if value == 2:
                                    鼠标单击坐标(963,532)
                                if value == 3:
                                    鼠标单击坐标(1063,532)
                                if value == 4:
                                    鼠标单击坐标(863,632)
                                if value == 5:
                                    鼠标单击坐标(963,632)
                                if value == 6:
                                    鼠标单击坐标(1063,632)
                                time.sleep(2)
                            鼠标单击坐标(1072,684)
                            time.sleep(7)
                        else:
                            break
                    if 需要再次按下==1:
                        鼠标单击坐标(1778, 999)
                        time.sleep(10.5)
                    while True:
                        print("当前等级",等级)
                        print("当前跑图次数",卖次数)
                        点击坐标 = self.模板匹配(16, 811, 127, 1106, "renwu.png")
                        if 点击坐标:
                            print("已经进图")
                            time.sleep(2)
                            break
                        点击坐标 = self.模板匹配(268, 468, 1500, 950, "fenghao.png")
                        if 点击坐标:
                            break
                        time.sleep(3)

                if 跑图 == 1:
                    self.大坝跑图()
                    卖次数 = 卖次数+1
                    检查等级 = 1
                if 新号 == 1:
                    # self.新手替换保险箱()
                    self.新手配置装备()
                    新号 = 0
                    保证回到主页退出()
            self.关闭游戏窗口()
            time.sleep(60)
            # ========== 释放旧 DLL，确保下次拿到干净实例 ==========
            self.日志("========== 释放旧 DLL ===========")
            try:
                self.dll.BEX_Shutdown()
                self.日志("[重启] BEX_Shutdown 已调用")
            except Exception as e:
                self.日志(f"[重启] BEX_Shutdown 异常(忽略): {type(e).__name__}: {e}")
            try:
                _h = self.dll._handle
                ctypes.windll.kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
                ctypes.windll.kernel32.FreeLibrary.restype = ctypes.c_int
                _ok = ctypes.windll.kernel32.FreeLibrary(_h)
                self.日志(f"[重启] FreeLibrary 已释放 DLL(handle=0x{_h:X}, ret={_ok})")
            except Exception as e:
                self.日志(f"[重启] FreeLibrary 异常(忽略): {type(e).__name__}: {e}")
            self.dll = None
            self.已初始化 = False
            self.日志("========== 旧 DLL 已完全释放，下次将重新加载 ===========")

            break

        self.日志("========== 主线程结束 ==========")
        return 是否完成

    def 返回首页(self):
        返回 = 0
        while True:

            点击坐标 = self.模板匹配(13, 879, 673, 1178, "cf.png")
            if 点击坐标:
                鼠标单击坐标(*点击坐标)
                time.sleep(2)
                按键单击(VK_SPACE, 1)
                time.sleep(2)
            else:
                按键单击(VK_SPACE, 1)
                time.sleep(2)
            点击坐标 = self.模板匹配(896, 986, 978, 1046, "4.png")
            if 点击坐标:
                按键单击(VK_TAB)
                time.sleep(2)
            点击坐标 = self.模板匹配(1184, 519, 1891, 1079, "daoju.png")
            if 点击坐标:
                鼠标单击坐标(*点击坐标)
                time.sleep(2)
                self.三级清包=1
                点击坐标 = self.模板匹配(884, 519, 1891, 1079, "chushou.png")
                if 点击坐标:
                    鼠标单击坐标(*点击坐标)
                    time.sleep(2)
                    鼠标单击坐标(1401, 731)
                    time.sleep(2)
                    鼠标单击坐标(1374, 781)
                    time.sleep(2)
                    按键单击(VK_ESCAPE);
                    time.sleep(2)
                    点击坐标 = self.模板匹配(1225, 895, 1318, 973, "zhengli.png")
                    if 点击坐标:
                        鼠标单击坐标(1224, 932)
                        time.sleep(2.5)
                        按键单击(VK_ESCAPE, 1)
                        time.sleep(2)
            点击坐标 = self.模板匹配(0, 432, 1675, 893, "kaitou1.png")
            if 点击坐标:
                鼠标单击坐标(461, 585)
                time.sleep(2.5)
            点击坐标 = self.模板匹配(0, 432, 1675, 893, "kaitou2.png")
            if 点击坐标:
                鼠标单击坐标(461, 585)
                time.sleep(2.5)
            点击坐标 = self.模板匹配(1225,895,1318,973, "zhengli.png")
            if 点击坐标:
                鼠标单击坐标(1224,932)
                time.sleep(2.5)
                按键单击(VK_ESCAPE,1)
                time.sleep(2)
            点击坐标 = self.模板匹配(1410, 755, 1872, 1032, "wumubiao.png")
            if 点击坐标:
                break
            点击坐标 = self.模板匹配(1410, 755, 1872, 1032, "daba.png")
            if 点击坐标:
                break
            点击坐标 = self.模板匹配(792, 827, 1133, 1015, "queren.png")
            if 点击坐标:
                返回 = 2
                break
            点击坐标 = self.模板匹配(268, 468, 1500, 950, "fenghao.png")
            if 点击坐标:
                break
        按键单击(VK_SPACE);
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(2)
        保证回到主页退出()
        return 返回

    def 新号模式(self):
        点击坐标 = self.模板匹配(913, 1037, 1017, 1090, "kongge.png")
        if 点击坐标:
            print("进入新手模式初始化状态")
        else:
            time.sleep(6.5)
            鼠标单击坐标(659, 448);
            time.sleep(2.5)
            鼠标单击坐标(983, 690);
            time.sleep(5.5)
        while True:
            点击坐标 = self.模板匹配(913, 1037, 1017, 1090, "kongge.png")
            if 点击坐标:
                break
            time.sleep(5)

        结果 = self.执行路线文件("新手路线1.txt")
        dengdaicishu = 0
        按键单击(VK_Z)
        time.sleep(16)
        while True:
            dengdaicishu += 1
            if dengdaicishu>12:
                dengdaicishu=0
            点击坐标 = self.模板匹配(268, 468, 1500, 950, "fenghao.png")
            if 点击坐标:
                break
            点击坐标 = self.模板匹配(896, 986, 978, 1046, "4.png")
            if 点击坐标:
                按键单击(VK_TAB)
                time.sleep(2)
            点击坐标 = self.模板匹配(1410, 755, 1872, 1032, "wumubiao.png")
            if 点击坐标:
                break
            点击坐标 = self.模板匹配(1410, 755, 1872, 1032, "daba.png")
            if 点击坐标:
                break
            点击坐标 = self.模板匹配(13, 879, 673, 1178, "kongge.png")
            if 点击坐标:
                按键单击(VK_ESCAPE);
                time.sleep(2)
                按键单击(VK_SPACE);
                time.sleep(2)
                按键单击(VK_SPACE);
                time.sleep(2)
                按键单击(VK_SPACE);
                time.sleep(2)
                按键单击(VK_SPACE);
                time.sleep(2)
                break
            点击坐标 = self.模板匹配(13, 879, 673, 1178, "cf.png")
            if 点击坐标:
                鼠标单击坐标(*点击坐标)
                time.sleep(2)
                按键单击(VK_SPACE, 1)
                time.sleep(2)
            按键单击(VK_SPACE);
            time.sleep(5)

            if dengdaicishu > 7:
                结果 = self.执行路线文件("新手路线2.txt")
                按键单击(VK_Z)
                time.sleep(16)
            #     dengdaicishu = 0
            if dengdaicishu > 8:
                按键单击(VK_ESCAPE);
                time.sleep(2)
        self.返回首页()
        保证回到主页退出()
        self.新手替换保险箱()
        return 结果

    def 大坝跑图(self):
        按键单击(VK_3)
        time.sleep(1.5)
        按键单击(VK_1)
        time.sleep(1.5)
        按键单击(VK_5)
        time.sleep(10)
        按键单击(VK_5)
        time.sleep(10)

        # ===== 自动选路：对比 die_1~die_14 的首行坐标 =====
        self.读坐标()
        当前x, 当前y, 当前z = self.px.value, self.py.value, self.pz.value
        self.日志(f"[选路] 当前位置=({当前x:.1f}, {当前y:.1f}, {当前z:.1f})")

        匹配距离 = 2500
        匹配文件 = None
        最近距离 = float("inf")
        最近文件 = None
        for 编号 in range(1, 15):
            文件 = f"die_{编号}.txt"
            if not os.path.exists(文件):
                continue
            try:
                with open(文件, "r", encoding="utf-8") as f:
                    首行 = next((l.strip() for l in f if l.strip()), "")
                if not 首行:
                    continue
                fx, fy, fz, _, _, _ = self.解析坐标行(首行)
            except Exception:
                continue
            d = math.sqrt((当前x - fx) ** 2 + (当前y - fy) ** 2 + (当前z - fz) ** 2)
            if d < 最近距离:
                最近距离 = d
                最近文件 = 文件
            if d <= 匹配距离 and 匹配文件 is None:
                匹配文件 = 文件

        #
        if 匹配文件 is None:
            return False
        文件名字 = 匹配文件
        # 文件名字="新手路线1.txt"

        self.日志(f"[选路] 选中 → {文件名字}")
        self.日志("========== 开始跑图 ==========")
        # time.sleep(5)
        结果 = self.执行路线文件(文件名字)
        结束次数=0
        while True:
            结束次数=结束次数+1


            按键单击(VK_SPACE);
            time.sleep(2.5)
            if 结束次数>40:
                按键单击(VK_ESCAPE);
                time.sleep(1)
                结束次数=0
            点击坐标 = self.模板匹配(13, 879, 673, 1178, "cf.png")
            if 点击坐标:
                鼠标单击坐标(*点击坐标)
                time.sleep(2)
                按键单击(VK_SPACE, 1)
                time.sleep(2)
            点击坐标 = self.模板匹配(887, 973, 1047, 1069, "eee.png")
            if 点击坐标:
                鼠标单击坐标(966, 675);
                time.sleep(1.5)
                鼠标单击坐标(1150, 710);
                time.sleep(3.5)
                break

            点击坐标 = self.模板匹配(13, 879, 673, 1178, "kongge.png")
            if 点击坐标:
                按键单击(VK_SPACE);
                time.sleep(2)
                break
            else:
                按键单击(VK_SPACE,5);
                time.sleep(1)
            点击坐标 = self.模板匹配(18,827,292,1107, "eee2.png")
            if 点击坐标:
                按键单击(VK_E);
                time.sleep(2)
                鼠标单击坐标(1130, 700)
                time.sleep(2.5)
                break
            点击坐标 = self.模板匹配(21,991,118,1069, "siwang.png",0.75)
            if 点击坐标:
                按键单击(VK_SPACE,8);
                time.sleep(2)
            点击坐标 = self.模板匹配(571,880,1283,1145, "siwang2.png",0.75)
            if 点击坐标:
                按键单击(VK_SPACE,8);
                time.sleep(2)
            点击坐标 = self.模板匹配(460,434,1471,865, "queren.png")
            if 点击坐标:
                鼠标单击坐标(806,723)
                time.sleep(2)
            点击坐标 = self.模板匹配(896, 986, 978, 1046, "4.png")
            if 点击坐标:
                break
                time.sleep(2)
            点击坐标 = self.模板匹配(18,827,292,1107, "eee2.png")
            if 点击坐标:
                按键单击(VK_E);
                time.sleep(2)
                鼠标单击坐标(1130, 700)
                time.sleep(2.5)
                break
            点击坐标 = self.模板匹配(268, 468, 1500, 950, "fenghao.png")
            if 点击坐标:
                break
        self.返回首页()
        return 结果

    def 新手替换保险箱(self):
        鼠标单击坐标(698, 1090);
        time.sleep(2.5)
        鼠标单击坐标(290, 378);
        time.sleep(2.5)
        鼠标单击坐标(207, 883);
        time.sleep(2.5)
        按键单击(VK_SPACE);
        time.sleep(2)
        按键单击(VK_ESCAPE);
        time.sleep(2)
        按键单击(VK_ESCAPE);
        time.sleep(2)
        鼠标单击坐标(336, 91);
        time.sleep(2.5)
        按键单击(VK_SPACE);
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(2)
        鼠标单击坐标(754, 920);
        time.sleep(2.5)
        鼠标单击坐标(277, 356);
        time.sleep(2.5)
        鼠标单击坐标(1764, 991);
        time.sleep(2.5)
        鼠标单击坐标(943, 740);
        time.sleep(2.5)
        鼠标单击坐标(1764, 991);
        time.sleep(2.5)
        按键单击(VK_ESCAPE);
        time.sleep(2)
        鼠标双击坐标(587, 802);
        time.sleep(1.5)
        鼠标双击坐标(508, 950);
        time.sleep(1.5)
        鼠标双击坐标(322, 1088);
        time.sleep(1.5)
        按键单击(VK_ESCAPE);
        time.sleep(2)

    def 新手配置装备(self):
        鼠标单击坐标(1585, 1005);
        time.sleep(2.5)
        按键单击(VK_SPACE, 1);
        time.sleep(1)
        按键单击(VK_SPACE, 1);
        time.sleep(1)
        鼠标单击坐标(395, 1085);
        time.sleep(2.5)
        鼠标单击坐标(231, 751);
        time.sleep(2.5)
        鼠标单击坐标(1056, 664);
        time.sleep(2.5)
        鼠标单击坐标(263, 531);
        time.sleep(2.5)
        鼠标单击坐标(1704, 973);
        time.sleep(2.5)
        鼠标单击坐标(1008, 774);
        time.sleep(2.5)
        鼠标单击坐标(349, 777);
        time.sleep(2.5)
        鼠标单击坐标(1704, 973);
        time.sleep(2.5)
        鼠标单击坐标(1086, 869);
        time.sleep(2.5)
        鼠标单击坐标(443, 478);
        time.sleep(2.5)
        鼠标单击坐标(256, 491);
        time.sleep(2.5)
        鼠标单击坐标(1704, 973);
        time.sleep(2.5)
        鼠标单击坐标(1064, 952);
        time.sleep(2.5)
        鼠标单击坐标(275, 898);
        time.sleep(2.5)
        鼠标单击坐标(1704, 973);
        time.sleep(2.5)
        鼠标单击坐标(1715, 976);
        time.sleep(2.5)
        鼠标单击坐标(947, 778);
        time.sleep(2.5)
        鼠标单击坐标(1718, 907);
        time.sleep(7.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        鼠标单击坐标(1692, 988);
        time.sleep(2.5)
        鼠标单击坐标(1022, 716);
        time.sleep(2.5)

    def 购买跨越生命线01任务药品(self):
        """在主页接取每日任务"""
        global ace
        鼠标单击坐标(1565, 998)  # 点击配装
        time.sleep(2)
        鼠标单击坐标(1782, 789)  # 点击携带药品
        time.sleep(2)
        鼠标单击坐标(1645, 922)  # 点击止痛片
        time.sleep(2)
        鼠标单击坐标(1645, 922)  # 点击止痛片
        time.sleep(2)
        鼠标单击坐标(1700, 982)  # 点击购买
        time.sleep(2)
        鼠标单击坐标(1649,408) #maiqiang
        time.sleep(2)
        鼠标单击坐标(1692,888)  # zhuangqiang
        time.sleep(2)
        鼠标单击坐标(1610,759)  # zidan
        time.sleep(2)
        鼠标单击坐标(1625,303)
        time.sleep(2)
        鼠标单击坐标(1625, 303)
        time.sleep(2)
        鼠标单击坐标(1625, 303)
        time.sleep(2)
        鼠标单击坐标(1625, 303)
        time.sleep(2)
        鼠标单击坐标(1685,977)
        time.sleep(2)
        鼠标单击坐标(1691, 982)  # 点击确认配备
        time.sleep(2)
        鼠标单击坐标(966, 735)  # 点击仍要继续
        time.sleep(2)
        ace = True


    def 任务_跨越生命线02(self):
        鼠标单击坐标(1691, 984)  # 点击跨越生命线02接取
        time.sleep(2)
        鼠标单击坐标(1401, 504)  # 点击前往完成任务
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        鼠标单击坐标(614, 582)  # 点击医疗部门
        time.sleep(2)
        鼠标单击坐标(302, 726)  # 点击简易手术包
        time.sleep(2)
        鼠标单击坐标(1652, 968)  # 点击购买
        time.sleep(2)
        鼠标单击坐标(307, 525)  # 点击止痛片
        time.sleep(2)
        鼠标单击坐标(1652, 968)  # 点击购买
        time.sleep(2)
        按键单击(VK_ESCAPE);
        time.sleep(0.5)
        鼠标单击坐标(211, 139)  # 部门任务
        time.sleep(2)
        鼠标单击坐标(651, 591)  # 跨越生命线
        time.sleep(2)
        鼠标单击坐标(1688, 984)  # 跨越生命线02领取
        time.sleep(2)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        鼠标单击坐标(1692, 985)  # 跨越生命线03接取
        time.sleep(2)
        按键单击(VK_ESCAPE);
        time.sleep(0.5)
        按键单击(VK_ESCAPE);
        time.sleep(0.5)
        按键单击(VK_ESCAPE);
        time.sleep(0.5)
        按键单击(VK_ESCAPE);  # 回到主页
        time.sleep(0.5)



    def 跨越生命线01领取(self):
        鼠标单击坐标(1691, 982)  # 点击震荡危情01任务领取
        time.sleep(2)
        鼠标单击坐标(1691, 983)  # 点击震荡危情02任务接取
        time.sleep(2)
        鼠标单击坐标(328, 110)  # 点击跨越生命线
        time.sleep(2)
        鼠标单击坐标(1692, 987)  # 点击跨越生命线01领取奖励
        time.sleep(2)
        按键单击(VK_SPACE)
        time.sleep(0.5)
        按键单击(VK_SPACE)
        time.sleep(0.5)
        按键单击(VK_SPACE)
        time.sleep(0.5)
        self.任务_跨越生命线02()

    def 启动前配置装备购买(self):

        鼠标单击坐标(1585, 1005);
        time.sleep(2.5)
        点击坐标 = self.模板匹配(1412,196,1943,873, "kaishixingdong.png")
        if 点击坐标:
            鼠标单击坐标(*点击坐标);
            time.sleep(1.5)
        按键单击(VK_SPACE, 1);
        time.sleep(2)
        鼠标单击坐标(395, 1085);
        time.sleep(2.5)
        鼠标单击坐标(231, 751);
        time.sleep(2.5)
        鼠标单击坐标(1718, 907);
        time.sleep(7.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        按键单击(VK_SPACE);
        time.sleep(0.5)
        鼠标单击坐标(1692, 988);
        time.sleep(2.5)
        鼠标单击坐标(1022, 716);
        time.sleep(2.5)

    # ----- 模板匹配识别 -----
    def 模板匹配(self, left, top, right, bottom, 模板图片路径, 阈值=0.8):
        try:
            import cv2
            模板 = cv2.imread(模板图片路径)
            if 模板 is None:
                self.日志(f"[模板匹配] 图片读取失败: {模板图片路径}")
                return None
            截图 = ImageGrab.grab(bbox=(left, top, right, bottom))
            偏移X, 偏移Y = left, top
            self.日志(f"[模板匹配] 区域搜索 ({left},{top},{right},{bottom})  模板={模板图片路径}")
            屏幕 = cv2.cvtColor(np.array(截图), cv2.COLOR_RGB2BGR)
            th, tw = 模板.shape[:2]
            sh, sw = 屏幕.shape[:2]
            if th > sh or tw > sw:
                self.日志("[模板匹配] 模板比搜索区域大，无法匹配")
                return None
            结果 = cv2.matchTemplate(屏幕, 模板, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(结果)
            if max_val >= 阈值:
                中心X = max_loc[0] + tw // 2 + 偏移X
                中心Y = max_loc[1] + th // 2 + 偏移Y
                self.日志(f"[模板匹配] 成功 ✓  相似度={round(max_val, 3)}  点击坐标=({中心X}, {中心Y})")
                return (中心X, 中心Y)
            else:
                self.日志(f"[模板匹配] 失败 ✗  相似度={round(max_val, 3)} < 阈值{阈值}")
                return None
        except ImportError:
            self.日志("[模板匹配] 缺依赖: pip install opencv-python pillow numpy")
            return None
        except Exception as e:
            self.日志(f"[模板匹配] 异常: {type(e).__name__}: {e}")
            return None

    def _弹窗错误(self, 消息, 标题="错误"):
        try:
            ctypes.windll.user32.MessageBoxW(0, str(消息), str(标题), 0x10 | 0x40000)
        except Exception as e:
            self.日志(f"[弹窗失败] {e}")

    # ----- 中断控制 -----
    def 请求停止(self):
        self.停止标志 = True
        按键松开(VK_W)
        self.日志("[*] 收到停止信号")

    # ----- 数据解析 -----
    @staticmethod
    def 解析坐标行(行):
        部分 = 行.split("----")
        位置 = 部分[0].split(",")
        x = float(位置[0]);
        y = float(位置[1]);
        z = float(位置[2])
        视角 = 部分[1].split(",")
        pitch = float(视角[0]);
        yaw = float(视角[1])
        try:
            动作 = int(部分[2].strip())
        except (IndexError, ValueError):
            动作 = -999
        return x, y, z, pitch, yaw, 动作

    # ----- 移动 + 视角 -----
    def 移动到目标(self, tx, ty, tz, 关闭冲刺=False):
        self.读坐标()
        self.读视角()
        距离 = math.sqrt((self.px.value - tx) ** 2 +
                         (self.py.value - ty) ** 2 +
                         (self.pz.value - tz) ** 2)
        _dx = tx - self.px.value
        _dy = ty - self.py.value
        _目标yaw = math.degrees(math.atan2(_dy, _dx))
        _yaw差 = 归一化角度(_目标yaw - self.yaw.value)
        self.日志(
            f"[调试当前] 坐标=({self.px.value:.2f}, {self.py.value:.2f}, {self.pz.value:.2f})  "
            f"视角(Pitch={self.pitch.value:.2f}, Yaw={self.yaw.value:.2f})"
        )
        self.日志(
            f"[调试目标] 坐标=({tx}, {ty}, {tz})  距离={距离:.2f}  "
            f"计算目标Yaw={_目标yaw:.2f}°  Yaw差={_yaw差:.2f}°  dx={_dx:.2f} dy={_dy:.2f}"
        )
        self.日志(f"[当前] 位置=({self.px.value:.1f}, {self.py.value:.1f}, "
                  f"{self.pz.value:.1f})  距离={距离:.1f}")

        if 距离 <= 坐标误差:
            self.日志("[到达] 已在误差范围内，无需移动")
            return

        self.日志(f"[移动] 距离 {距离:.1f} > 误差 {坐标误差}, 边走边校准...(超时={移动超时秒}秒)")
        按键按下(VK_W)
        shift状态 = False
        保存距离=距离
        if 距离 > 500 and not 关闭冲刺:
            # 按 Shift 之前先做模板匹配：识别到障碍 → 按 X 翻越；识别不到 → 才按 Shift 冲刺
            _点 = self.模板匹配(*攀爬识别范围, 攀爬识别模板, 阈值=攀爬识别阈值)
            if _点 is not None:
                self.日志(f"[攀爬] 识别到模板 {攀爬识别模板} → 按 X {攀爬按X时长}s 翻越")
                按键按下(VK_X)
                time.sleep(攀爬按X时长)
                按键松开(VK_X)
            else:
                点击坐标 = self.模板匹配(0, 1000, 400, 1050, "xuetiao.png")
                if 点击坐标:
                    pass
                else:
                    self.日志(f"[攀爬] 识别到模板 {攀爬识别模板} → 按 X {攀爬按X时长}s 翻越")
                    按键按下(VK_X)
                    time.sleep(攀爬按X时长)
                    按键松开(VK_X)
                    time.sleep(0.1)

                按键按下(VK_SHIFT)
                shift状态 = True
                self.日志(f"[Shift] 距离 {距离:.0f} > 300 → 按住 Shift 冲刺")
        起始时间 = time.time()
        计数 = 0
        已卡住处理 = False  # 10 秒卡住自救只触发一次
        try:
            while not self.停止标志:
                已用 = time.time() - 起始时间
                if 已用 > 移动超时秒:
                    raise 移动超时异常(
                        f"前进 {移动超时秒} 秒仍未到位，剩余距离={距离:.1f}"
                    )

                # 10 秒卡住自救：长按 F 2 秒 + 跳 2 次，只触发一次
                if 已用 < 2 and not 已卡住处理:
                    # 点击坐标 = self.模板匹配(1100, 559, 1182, 626, "kaimen.png")
                    # if 点击坐标:
                    #     self.日志("[动作3] 按下 F 键")
                    #     按键单击(VK_F)
                    点击坐标 = self.模板匹配(552, 581, 796, 824, "QQ.png",0.9)
                    if 点击坐标:
                        按键单击(VK_ESCAPE)

                if 已用 > 10 and not 已卡住处理:
                    self.日志(f"[卡住自救] 移动已 {已用:.1f}s，长按 F 2 秒 → 跳 2 次")
                    按键按下(VK_F)
                    time.sleep(2)
                    按键松开(VK_F)
                    按键单击(VK_SPACE)
                    time.sleep(0.3)
                    按键单击(VK_SPACE)
                    time.sleep(0.3)
                    已卡住处理 = True
                time.sleep(0.1)
                self.读坐标()
                距离 = math.sqrt((self.px.value - tx) ** 2 +
                                 (self.py.value - ty) ** 2 +
                                 (self.pz.value - tz) ** 2)
                计数 += 1

                if 计数 % 2 == 0:
                    self.读视角()
                    dx = tx - self.px.value
                    dy = ty - self.py.value
                    目标yaw = math.degrees(math.atan2(dy, dx))
                    yaw差 = 归一化角度(目标yaw - self.yaw.value)
                    if abs(yaw差) > 0.5:
                        转动量 = yaw差 * FPS_灵敏度
                        self.日志(
                            f"[转前] 坐标=({self.px.value:.1f},{self.py.value:.1f},{self.pz.value:.1f})  "
                            f"视角(P={self.pitch.value:.2f},Y={self.yaw.value:.2f})  "
                            f"目标Yaw={目标yaw:.2f}  Yaw差={yaw差:.2f}°  转动量={转动量:.1f}像素"
                        )
                        FPS视角转动(转动量, 0)
                        time.sleep(0.05)
                        self.读坐标()
                        self.读视角()
                        残余 = 归一化角度(目标yaw - self.yaw.value)
                        self.日志(
                            f"[转后] 坐标=({self.px.value:.1f},{self.py.value:.1f},{self.pz.value:.1f})  "
                            f"视角(P={self.pitch.value:.2f},Y={self.yaw.value:.2f})  "
                            f"残余Yaw差={残余:.2f}°  实际转动={(yaw差 - 残余):.2f}°"
                        )
                        if abs(残余) > 0.5:
                            补转动量 = 残余 * FPS_灵敏度
                            self.日志(f"[补转前] 补转量={补转动量:.1f}像素")
                            FPS视角转动(补转动量, 0)
                            time.sleep(0.05)
                            self.读视角()
                            self.日志(
                                f"[补转后] 视角(P={self.pitch.value:.2f},Y={self.yaw.value:.2f})  "
                                f"最终偏差={归一化角度(目标yaw - self.yaw.value):.2f}°"
                            )

                if 计数 % 10 == 0:
                    self.读视角()
                    dx = tx - self.px.value
                    dy = ty - self.py.value
                    目标yaw = math.degrees(math.atan2(dy, dx))
                    偏差 = abs(归一化角度(目标yaw - self.yaw.value))
                    self.日志(f"  移动中... 距离={距离:.1f}  方向偏差={偏差:.2f}°")

                if 距离 <= 坐标误差:
                    break

                if 距离 > 500 and not shift状态 and not 关闭冲刺:
                    # 按 Shift 之前先做模板匹配：识别到障碍 → 按 X 翻越；识别不到 → 才按 Shift
                    _点 = self.模板匹配(*攀爬识别范围, 攀爬识别模板, 阈值=攀爬识别阈值)
                    if _点 is not None:
                        self.日志(f"[攀爬] 识别到模板 {攀爬识别模板} → 按 X {攀爬按X时长}s 翻越")
                        按键按下(VK_X)
                        time.sleep(攀爬按X时长)
                        按键松开(VK_X)
                    else:
                        按键按下(VK_SHIFT)
                        shift状态 = True
                        self.日志(f"[Shift] 距离 {距离:.0f} > 300 → 按住 Shift")
                elif 距离 <= 500 and shift状态:
                    按键松开(VK_SHIFT)
                    shift状态 = False
                    self.日志(f"[Shift] 距离 {距离:.0f} ≤ 300 → 松开 Shift")
        finally:
            按键松开(VK_W)
            按键松开(VK_SHIFT)

        self.日志(f"[到达] 距离={距离:.1f} <= 误差{坐标误差}, 停止移动")

    def 转动视角(self, tp, tw):
        self.读视角()
        当前pitch = self.pitch.value
        当前yaw = self.yaw.value
        self.日志(f"[调试视角] 当前(Pitch={当前pitch:.2f}, Yaw={当前yaw:.2f})  "
                  f"目标(Pitch={tp}, Yaw={tw})  灵敏度={FPS_灵敏度}")
        self.日志(f"[当前视角] Pitch={当前pitch:.2f}  Yaw={当前yaw:.2f}")

        for 轮次 in range(视角校正次数):
            yaw差 = 归一化角度(tw - 当前yaw)
            pitch差 = tp - 当前pitch
            dx = yaw差 * FPS_灵敏度
            dy = -(pitch差 * FPS_灵敏度)

            if 轮次 == 0:
                self.日志(f"[视角计算] Yaw差={yaw差:.2f}  Pitch差={pitch差:.2f}  "
                          f"鼠标=({dx:.1f}, {dy:.1f})")

            if abs(yaw差) <= 视角误差 and abs(pitch差) <= 视角误差:
                if 轮次 == 0:
                    self.日志(f"[视角] 已在 {视角误差}° 误差内")
                break

            # 记录转动前的快照
            转前pitch = 当前pitch
            转前yaw = 当前yaw

            FPS视角转动(dx, dy)

            # 等待视角停稳：连续2次读取值变化<0.5°说明已停止滑动
            上次pitch = self.pitch.value
            上次yaw = self.yaw.value
            连续稳定次数 = 0
            for _ in range(15):  # 最多等 15×50ms = 0.75秒
                time.sleep(0.05)
                self.读视角()
                if (abs(self.pitch.value - 上次pitch) < 0.5 and
                        abs(归一化角度(self.yaw.value - 上次yaw)) < 0.5):
                    连续稳定次数 += 1
                    if 连续稳定次数 >= 2:
                        break
                else:
                    连续稳定次数 = 0
                上次pitch = self.pitch.value
                上次yaw = self.yaw.value

            当前pitch = self.pitch.value
            当前yaw = self.yaw.value
            实yaw = abs(归一化角度(tw - 当前yaw))
            实pitch = abs(tp - 当前pitch)

            if 实yaw <= 视角误差 and 实pitch <= 视角误差:
                self.日志(f"[视角校正] 第{轮次 + 1}次到位  Yaw={实yaw:.2f}°  Pitch={实pitch:.2f}°")
                break
            else:
                self.日志(f"[视角校正] 第{轮次 + 1}次  Yaw={实yaw:.2f}°  Pitch={实pitch:.2f}° → 继续")

    # ----- 动作分发 -----
    def 执行动作(self, 代码):
        分发 = {
            0: self.动作0_无,
            1: self.动作1_左键2秒,
            2: self.动作2_F等4秒ESC,
            3: self.动作3_按F,
            4: self.动作4_占位,
            5: self.动作5_X左击,
            6: self.动作6_M两下,
            10: self.动作10_瘂28秒,
            11: self.动作11_右键循环左点,
            22: self.动作22_D加动作2,
            101: self.动作101_空格等2秒,
            333: self.动作333_W跳1次,
            334: self.动作334_W跳2次,
            335: self.动作335_W跳3次,
        }
        函数 = 分发.get(代码)
        if 函数:
            函数()
        else:
            self.日志(f"[动作] 未知动作代码: {代码}")
            time.sleep(8)

    # ----- 动作子方法 -----
    def 动作0_无(self):
        self.日志("[动作0] 无动作继续跑")

    def 动作1_左键2秒(self):
        self.日志("[动作1] 按住鼠标左键 2 秒")
        鼠标左键按下()
        time.sleep(2)
        鼠标左键松开()
        time.sleep(1)

    def 动作2_F等4秒ESC(self):
        time.sleep(0.6)
        self.日志("[动作2] 按 F → 等 4 秒 → 按 ESC")
        按键单击(VK_F)
        time.sleep(1.3)
        打开物资=0
        # 【新增这一行】告诉Python，下面的变量使用的是外部变量，不要创建新的局部变量
        global 动作2扫描_上偏移, 动作2扫描_下偏移, 动作2扫描_左偏移, 动作2扫描_右偏移

        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
        if 点击坐标:
            打开物资 = 1
            pass
        else:
            # time.sleep(2)
            点击坐标 = self.模板匹配(420,149,1618,975, "kaimen.png",0.97)
            if 点击坐标:
                print("----------------------------------------------------------可直接拾取状态")
                按键单击(VK_F)
                time.sleep(1.3)
                return 1
            旧版转向=0

            if 旧版转向==0:
                self.读视角()
                原始pitch = self.pitch.value
                原始yaw = self.yaw.value
                iii次数=1
                for iiii in range(4):
                    if iii次数==1:
                        self.转动视角(原始pitch + 动作2扫描_上偏移, 原始yaw)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        self.转动视角(原始pitch - 动作2扫描_下偏移, 原始yaw)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        self.转动视角(原始pitch, 原始yaw - 动作2扫描_左偏移)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        self.转动视角(原始pitch, 原始yaw + 动作2扫描_右偏移)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                    if iii次数==2:
                        动作2扫描_上偏移2=动作2扫描_上偏移/2
                        self.转动视角(原始pitch + 动作2扫描_上偏移2, 原始yaw)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        动作2扫描_下偏移2=动作2扫描_下偏移/2
                        self.转动视角(原始pitch - 动作2扫描_下偏移2, 原始yaw)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        动作2扫描_左偏移2=动作2扫描_左偏移/2
                        self.转动视角(原始pitch, 原始yaw - 动作2扫描_左偏移2)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        动作2扫描_右偏移2=动作2扫描_右偏移/2
                        self.转动视角(原始pitch, 原始yaw + 动作2扫描_右偏移2)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                    if iii次数==3:
                        动作2扫描_上偏移2=动作2扫描_上偏移*2
                        self.转动视角(原始pitch + 动作2扫描_上偏移2, 原始yaw)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        动作2扫描_下偏移2=动作2扫描_下偏移*2
                        self.转动视角(原始pitch - 动作2扫描_下偏移2, 原始yaw)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        动作2扫描_左偏移2=动作2扫描_左偏移*2
                        self.转动视角(原始pitch, 原始yaw - 动作2扫描_左偏移2)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                        动作2扫描_右偏移2=动作2扫描_右偏移*2
                        self.转动视角(原始pitch, 原始yaw + 动作2扫描_右偏移2)
                        time.sleep(0.1)
                        按键单击(VK_F)
                        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                        if 点击坐标:
                            打开物资 = 1
                            break
                    iii次数=iii次数+1
                pass








            旧版转向=0
            if 旧版转向==1:
                点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
                if 点击坐标:
                    pass
                else:
                    # ========== 动作2失败 → 视角扫描 + 动作3 ==========
                    self.日志("[动作2] QQ.png 未识别到，开始视角扫描尝试动作2")
                    self.读视角()
                    原始pitch = self.pitch.value
                    原始yaw = self.yaw.value
                    self.日志(f"[扫描] 当前视角 pitch={原始pitch:.2f}  yaw={原始yaw:.2f}")

                    # ↑ 上
                    self.日志(f"[扫描-上] 偏移 pitch+{动作2扫描_上偏移}")
                    self.转动视角(原始pitch + 动作2扫描_上偏移, 原始yaw)
                    if self.动作2_F等4秒ESC2() == 1:
                        self.日志("[扫描] 上方匹配成功，退出扫描")
                        return 0

                    # ↓ 下
                    self.日志(f"[扫描-下] 偏移 pitch-{动作2扫描_下偏移}")
                    self.转动视角(原始pitch - 动作2扫描_下偏移, 原始yaw)
                    if self.动作2_F等4秒ESC2() == 1:
                        self.日志("[扫描] 下方匹配成功，退出扫描")
                        return 0

                    # ← 左
                    self.日志(f"[扫描-左] 偏移 yaw-{动作2扫描_左偏移}")
                    self.转动视角(原始pitch, 原始yaw - 动作2扫描_左偏移)
                    if self.动作2_F等4秒ESC2() == 1:
                        self.日志("[扫描] 左方匹配成功，退出扫描")
                        return 0

                    # → 右
                    self.日志(f"[扫描-右] 偏移 yaw+{动作2扫描_右偏移}")
                    self.转动视角(原始pitch, 原始yaw + 动作2扫描_右偏移)
                    if self.动作2_F等4秒ESC2() == 1:
                        self.日志("[扫描] 右方匹配成功，退出扫描")
                        return 0

                    self.日志("[扫描] 四个方向均未识别到，扫描结束")
                    # exit()

                    # ========== 扫描结束 ==========
                    return 0

        if 打开物资 ==0:
            return 0
        for i in range(16):
            点击坐标 = self.模板匹配(1258, 72, 1785, 952, "soso.png")
            if 点击坐标:
                time.sleep(0.5)
                识别物资点击2()
            else:
                break
            time.sleep(0.5)
        重试次数=0
        替换重试次数=0
        for i in range(5):
            鼠标移动到(5,5)
            time.sleep(0.2)
            fanhui=识别物资点击2(i)
            if fanhui==0:
                重试次数 = 重试次数+1
            if 重试次数>0:
                break
            if i>2 and fanhui==1:
                if 替换重试次数 > 0:
                    break
                print("已经满背包  扔掉背包的垃圾")
                print('拿走所有的绿色')
                for ihg in range(5):
                    # result = search_color_center(target_rgb=(24, 36, 31), region=(875, 518, 1204, 999), tolerance=1)
                    # if result:
                    #     x, y, count = result
                    #     print(f"中心坐标: ({x}, {y})  匹配像素数: {count}")
                    #     鼠标双击坐标(x, y)
                    #     time.sleep(0.5)
                    # 金色物资
                    点击坐标 = 模板匹配(875, 480, 1204, 999, "lvse.png", 0.98)
                    if 点击坐标:
                        print("绿色物资")
                        鼠标双击坐标(*点击坐标)
                        time.sleep(0.5)
                        组合键ALT_D()
                    点击坐标 = 模板匹配(875, 480, 1204, 999, "lvse2.png", 0.98)
                    if 点击坐标:
                        print("绿色物资")
                        鼠标双击坐标(*点击坐标)
                        time.sleep(0.5)
                        组合键ALT_D()

                time.sleep(0.1)
                替换重试次数 = 替换重试次数+1

        for i in range(3):
            result = search_color_center(target_rgb=(24, 36, 31), region=(1254, 105, 1739, 940), tolerance=1)
            if result:
                x, y, count = result
                print(f"中心坐标: ({x}, {y})  匹配像素数: {count}")
                鼠标双击坐标(x, y)
                time.sleep(0.5)
            else:
                break
        print('拿走保险箱的绿色')
        result = search_color_center(target_rgb=(24, 36, 31), region=(875, 812, 1092, 997), tolerance=1)
        if result:
            x, y, count = result
            print(f"中心坐标: ({x}, {y})  匹配像素数: {count}")
            鼠标双击坐标(x, y)
            time.sleep(0.5)



        按键单击(VK_ESCAPE)
        time.sleep(1)
        点击坐标 = self.模板匹配(887, 973, 1047, 1069, "eee.png")
        if 点击坐标:
            按键单击(VK_ESCAPE)
            time.sleep(1)
        return 1
    def 识别文字(self):
        def image_to_base64(img_path):
            """读取本地图片并转成 base64 字符串"""
            with open(img_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')

        def ocr_by_base64(img_path, mode='mixed', scale=1, padding=0, detail=0):
            """
            通过 base64 上传图片到 RapidOCR 服务端识别。
            :param img_path: 本地图片路径
            :param mode:     识别模式: digit / english / chinese / mixed
            :param scale:    整数倍放大，默认 1；小图识别不准时可试 2 或 3
            :param padding:  四周加白边像素数，默认 0；字符贴边漏识别时试 8~20
            :param detail:   0=只返回文本字符串；1=返回每块 box+text+score
            """
            SERVER_URL = "http://106.52.36.160:10828/ocr"
            payload = {
                "image_base64": image_to_base64(img_path),
                "mode": mode,
                "scale": scale,
                "padding": padding,
                "detail": detail,
            }
            t0 = time.time()
            resp = requests.post(SERVER_URL, json=payload, timeout=60)
            print(resp)
            cost_ms = (time.time() - t0) * 1000
            data = resp.json()

            if data.get("code") == 0:
                print("[识别成功][mode=%s][scale=%d][pad=%d][detail=%d][耗时=%.1fms]"
                      % (data.get("mode", mode), scale, padding, detail, cost_ms))
                result = data["result"]
                if isinstance(result, list):
                    for item in result:
                        print("  ", item)
                else:

                    print("  =>", repr(result))
            else:
                print("[识别失败]", data.get("msg"))
            clean_text = result.replace("\n", "")
            print(clean_text)
            return clean_text

        def img_to_base64(img_path):
            with open(img_path, 'rb') as read:
                b64 = base64.b64encode(read.read())
            return b64

        # 替换 URL=http://116.204.132.93:8089/
        url = 'http://116.204.132.93:8089//api/tr-run/'

        # 截图保存指定范围 (1513,834,1693,869) 为 AAA.png
        self.capture_screenshot((197,666,238,706), 'AAA.png')
        time.sleep(0.2)
        验证模式 = 3
        if 验证模式 == 3:
            # ========== 修改为你要识别的图片路径 ==========
            test_image = 'AAA.png'
            # ==============================================

            # mode 可选: digit(只数字) / english(只英文) / chinese(只中文) / mixed(混合)
            test_mode = 'mixed'

            # === 可选预处理参数（一般不用动；图很小或字符贴边时再调） ===
            test_scale = 1  # 图片整数倍放大，小图建议 2~3
            test_padding = 1  # 四周加白边像素数，字符贴边漏识别时建议 10~20

            # 0 = 只返回文本字符串；1 = 返回每块 box+text+score 详细信息
            test_detail = 0

            # print("=" * 50)
            # print("【RapidOCR base64 识别】mode=%s scale=%d padding=%d detail=%d"
            #       % (test_mode, test_scale, test_padding, test_detail))
            # print("=" * 50)
            sdads = ocr_by_base64(test_image,
                                  mode=test_mode,
                                  scale=test_scale,
                                  padding=test_padding,
                                  detail=test_detail)
            print(len(sdads))
            return sdads
    def 识别文字2(self):
        def image_to_base64(img_path):
            """读取本地图片并转成 base64 字符串"""
            with open(img_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')

        def ocr_by_base64(img_path, mode='mixed', scale=1, padding=0, detail=0):
            """
            通过 base64 上传图片到 RapidOCR 服务端识别。
            :param img_path: 本地图片路径
            :param mode:     识别模式: digit / english / chinese / mixed
            :param scale:    整数倍放大，默认 1；小图识别不准时可试 2 或 3
            :param padding:  四周加白边像素数，默认 0；字符贴边漏识别时试 8~20
            :param detail:   0=只返回文本字符串；1=返回每块 box+text+score
            """
            SERVER_URL = "http://106.52.36.160:10828/ocr"
            payload = {
                "image_base64": image_to_base64(img_path),
                "mode": mode,
                "scale": scale,
                "padding": padding,
                "detail": detail,
            }
            t0 = time.time()
            resp = requests.post(SERVER_URL, json=payload, timeout=60)
            print(resp)
            cost_ms = (time.time() - t0) * 1000
            data = resp.json()

            if data.get("code") == 0:
                print("[识别成功][mode=%s][scale=%d][pad=%d][detail=%d][耗时=%.1fms]"
                      % (data.get("mode", mode), scale, padding, detail, cost_ms))
                result = data["result"]
                if isinstance(result, list):
                    for item in result:
                        print("  ", item)
                else:

                    print("  =>", repr(result))
            else:
                print("[识别失败]", data.get("msg"))
            clean_text = result.replace("\n", "")
            print(clean_text)
            return clean_text

        def img_to_base64(img_path):
            with open(img_path, 'rb') as read:
                b64 = base64.b64encode(read.read())
            return b64

        # 替换 URL=http://116.204.132.93:8089/
        url = 'http://116.204.132.93:8089//api/tr-run/'

        # 截图保存指定范围 (1513,834,1693,869) 为 AAA.png
        self.capture_screenshot((1486,63,1631,98), 'AAA.png')
        time.sleep(0.2)
        验证模式 = 3
        if 验证模式 == 3:
            # ========== 修改为你要识别的图片路径 ==========
            test_image = 'AAA.png'
            # ==============================================

            # mode 可选: digit(只数字) / english(只英文) / chinese(只中文) / mixed(混合)
            test_mode = 'mixed'

            # === 可选预处理参数（一般不用动；图很小或字符贴边时再调） ===
            test_scale = 1  # 图片整数倍放大，小图建议 2~3
            test_padding = 1  # 四周加白边像素数，字符贴边漏识别时建议 10~20

            # 0 = 只返回文本字符串；1 = 返回每块 box+text+score 详细信息
            test_detail = 0

            # print("=" * 50)
            # print("【RapidOCR base64 识别】mode=%s scale=%d padding=%d detail=%d"
            #       % (test_mode, test_scale, test_padding, test_detail))
            # print("=" * 50)
            sdads = ocr_by_base64(test_image,
                                  mode=test_mode,
                                  scale=test_scale,
                                  padding=test_padding,
                                  detail=test_detail)
            print(len(sdads))
            return sdads


    def 动作2_F等4秒ESC2(self):
        time.sleep(0.4)
        self.日志("[动作2] 按 F → 等 4 秒 → 按 ESC")
        按键单击(VK_F)
        time.sleep(1.3)
        点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
        if 点击坐标:
            pass
        else:
            time.sleep(2)
            点击坐标 = self.模板匹配(552,581,796,824, "QQ.png")
            if 点击坐标:
                pass
            else:
                return 0

        for i in range(16):
            点击坐标 = self.模板匹配(1258, 72, 1785, 952, "soso.png")
            if 点击坐标:
                time.sleep(0.5)
            else:
                break
            time.sleep(0.5)
        识别物资点击()
        识别物资点击()
        识别物资点击()
        识别物资点击()
        按键单击(VK_ESCAPE)
        time.sleep(1)
        点击坐标 = self.模板匹配(887, 973, 1047, 1069, "eee.png")
        if 点击坐标:
            按键单击(VK_ESCAPE)
            time.sleep(1)
        return 1
    def capture_screenshot(self, region, save_path):
        """截图指定范围并保存

        参数:
            region: 截图范围 (left, top, right, bottom)
            save_path: 保存路径
        """
        try:
            from PIL import ImageGrab

            # 在指定范围内截图
            left, top, right, bottom = region
            screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))

            # 保存截图
            screenshot.save(save_path)
            # self.log_signal.emit("    截图已保存至：" + save_path + "，区域：( " + str(left) + ", " + str(top) + ", " + str(right) + ", " + str(bottom) + " )")
        except Exception as e:
            print("    截图保存出错：" + str(e))
    def 动作3_按F(self):
        time.sleep(0.6)
        点击坐标 = self.模板匹配(1100, 559, 1182, 626, "kaimen.png")
        if 点击坐标:
            self.日志("[动作3] 识别到 kaimen.png")
            # 测试没问题,  一个月十块钱 不限制设备
            def image_to_base64(img_path):
                """读取本地图片并转成 base64 字符串"""
                with open(img_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')

            def ocr_by_base64(img_path, mode='mixed', scale=1, padding=0, detail=0):
                """
                通过 base64 上传图片到 RapidOCR 服务端识别。
                :param img_path: 本地图片路径
                :param mode:     识别模式: digit / english / chinese / mixed
                :param scale:    整数倍放大，默认 1；小图识别不准时可试 2 或 3
                :param padding:  四周加白边像素数，默认 0；字符贴边漏识别时试 8~20
                :param detail:   0=只返回文本字符串；1=返回每块 box+text+score
                """
                SERVER_URL = "http://106.52.36.160:10828/ocr"
                payload = {
                    "image_base64": image_to_base64(img_path),
                    "mode": mode,
                    "scale": scale,
                    "padding": padding,
                    "detail": detail,
                }
                t0 = time.time()
                resp = requests.post(SERVER_URL, json=payload, timeout=60)
                print(resp)
                cost_ms = (time.time() - t0) * 1000
                data = resp.json()

                if data.get("code") == 0:
                    print("[识别成功][mode=%s][scale=%d][pad=%d][detail=%d][耗时=%.1fms]"
                          % (data.get("mode", mode), scale, padding, detail, cost_ms))
                    result = data["result"]
                    if isinstance(result, list):
                        for item in result:
                            print("  ", item)
                    else:

                        print("  =>", repr(result))
                else:
                    print("[识别失败]", data.get("msg"))
                clean_text = result.replace("\n", "")
                print(clean_text)
                return clean_text

            def img_to_base64(img_path):
                with open(img_path, 'rb') as read:
                    b64 = base64.b64encode(read.read())
                return b64

            # 替换 URL=http://116.204.132.93:8089/
            url = 'http://116.204.132.93:8089//api/tr-run/'

            # 截图保存指定范围 (1513,834,1693,869) 为 AAA.png
            self.capture_screenshot((1152,575,1195,612), 'AAA.png')
            time.sleep(0.2)
            验证模式 = 3
            if 验证模式 == 3:
                # ========== 修改为你要识别的图片路径 ==========
                test_image = 'AAA.png'
                # ==============================================

                # mode 可选: digit(只数字) / english(只英文) / chinese(只中文) / mixed(混合)
                test_mode = 'mixed'

                # === 可选预处理参数（一般不用动；图很小或字符贴边时再调） ===
                test_scale = 1  # 图片整数倍放大，小图建议 2~3
                test_padding = 1  # 四周加白边像素数，字符贴边漏识别时建议 10~20

                # 0 = 只返回文本字符串；1 = 返回每块 box+text+score 详细信息
                test_detail = 0

                # print("=" * 50)
                # print("【RapidOCR base64 识别】mode=%s scale=%d padding=%d detail=%d"
                #       % (test_mode, test_scale, test_padding, test_detail))
                # print("=" * 50)
                sdads = ocr_by_base64(test_image,
                                      mode=test_mode,
                                      scale=test_scale,
                                      padding=test_padding,
                                      detail=test_detail)
                print(len(sdads))
                if "开" in sdads:
                    按键单击(VK_F)
                    time.sleep(0.5)
                    return 1
                if "长" in sdads:
                    按键单击(VK_F,2)
                    time.sleep(0.5)
                    return 1
            self.日志("[动作3] 识别到kaimen但OCR未匹配开/长")
            return 0
        else:
            self.日志("[动作3] 未识别到 kaimen.png")
            return 0
    def 动作4_占位(self):
        self.日志("[动作4] 待定义")
        time.sleep(8)

    def 动作5_X左击(self):
        self.日志("[动作5] 前进 2 秒 → 按 X → 鼠标左击一次 → 等 5 秒")
        按键按下(VK_W)
        time.sleep(2)
        按键松开(VK_W)
        time.sleep(0.1)
        按键单击(VK_X)
        time.sleep(2.1)
        鼠标左键单击()
        self.日志("[动作5] 完成")
        time.sleep(2)

    def 动作6_M两下(self):
        self.日志("[动作6] 按 M → 等 2 秒 → 按 M → 按 R → 等 1 秒")
        按键单击(VK_M);
        time.sleep(2)
        按键单击(VK_M)
        按键单击(VK_R);
        time.sleep(1)

    def 动作22_D加动作2(self):
        self.日志("[动作22] 按 D 0.1秒 → 执行动作2内容")
        按键按下(VK_D)
        time.sleep(0.1)
        按键松开(VK_D)
        按键按下(VK_S)
        time.sleep(0.1)
        按键松开(VK_S)
        self.新手动作特殊拿东西()
    def 新手动作特殊拿东西(self):
        按键单击(VK_F)
        time.sleep(1.3)
        time.sleep(0.4)
        鼠标双击坐标(1400, 250)
        time.sleep(1)
        鼠标双击坐标(1400, 250)
        time.sleep(1)

        鼠标双击坐标(1400, 350)
        time.sleep(1)



        鼠标双击坐标(1500, 350)
        time.sleep(1)


        鼠标双击坐标(1360, 652)
        time.sleep(1)














        鼠标单击坐标(1383, 941)
        time.sleep(1)

        鼠标单击坐标(1573,829)

        time.sleep(1)


        鼠标双击坐标(1341, 677)
        time.sleep(2)

        result = search_color_center(target_rgb=(33, 44, 54), region=(1254, 105, 1739, 940), tolerance=1)
        if result:
            x, y, count = result
            print(f"藏青色物资中心坐标: ({x}, {y})  匹配像素数: {count}")


            鼠标双击坐标(1329, y)
            time.sleep(1)
            鼠标双击坐标(1400, y)
            time.sleep(1)
            鼠标双击坐标(1460, y)
            time.sleep(1)
            鼠标双击坐标(1757, y)
            time.sleep(1)







        按键单击(VK_ESCAPE)
        time.sleep(1)
        return 1
    def 动作10_瘂28秒(self):
        return
        self.日志("[动作10] 等待 28 秒")
        识别密码箱点击密码()

    def 动作101_空格等2秒(self):
        time.sleep(2)
        self.日志("[动作101] 按下空格 → 等 2 秒")
        按键单击(VK_SPACE)
        time.sleep(2)

    # ----- 跳跃动作（W按住 + 空格 + 1秒后松W）-----
    def _跳一次(self):
        按键按下(VK_W)
        time.sleep(0.1)
        按键单击(VK_SPACE)
        time.sleep(1)
        按键松开(VK_W)

    def 动作333_W跳1次(self):
        self.日志("[动作333] 跳 1 次")
        self._跳一次()

    def 动作334_W跳2次(self):
        self.日志("[动作334] 跳 2 次")
        for i in range(2):
            self._跳一次()

    def 动作335_W跳3次(self):
        self.日志("[动作335] 跳 3 次")
        for i in range(3):
            self._跳一次()

    def 动作11_右键循环左点(self):
        self.日志("[动作11] D 0.1秒 → 按住右键 → 循环左点 → 松右键 → 前进 → 空格")
        按键按下(VK_D);
        time.sleep(0.1);
        按键松开(VK_D)
        鼠标右键按下();
        time.sleep(0.1)
        for 循环 in range(7):
            if self.停止标志:
                break
            self.日志(f"  [循环{循环 + 1}/7] 前三下...")
            for _ in range(3):
                鼠标左键单击()
                time.sleep(0.2)
            time.sleep(0.5)
        鼠标右键松开()
        time.sleep(0.2)
        鼠标右键松开()
        time.sleep(0.2)
        鼠标右键单击()
        time.sleep(0.3)
        鼠标右键松开()
        time.sleep(0.3)
        self.日志("  [动作11] 按 W 前进 3 秒")
        按键按下(VK_W)
        time.sleep(3)
        按键松开(VK_W)

        time.sleep(0.1)
        按键单击(VK_SPACE)
        time.sleep(2)
        鼠标右键单击()
        鼠标右键松开()
        time.sleep(0.3)
        time.sleep(1)
        鼠标右键松开()
        time.sleep(0.3)
        time.sleep(1)
    # ----- 路线文件执行入口 -----
    def 执行路线文件(self, 文件名=""):
        global ace
        self.停止标志 = False

        if not self.已初始化:
            if not self.初始化():
                return False
        关闭shift = 0
        if 文件名 == "新手路线1.txt":
            按键单击(VK_SPACE)
            time.sleep(2)
            关闭shift = 1
            设置鼠标()
        self.日志("\n========== 开始执行路线文件 ==========")
        self.日志(f"文件名: {文件名}")

        if not os.path.exists(文件名):
            self.日志(f"[ERROR] 文件不存在: {文件名}")
            return False

        with open(文件名, "r", encoding="utf-8") as f:
            坐标列表 = [l.strip() for l in f.readlines() if l.strip()]

        self.日志(f"[*] 共读取 {len(坐标列表)} 个坐标点")
        self.日志(f"[*] 坐标误差={坐标误差}  视角误差={视角误差}°  校正次数={视角校正次数}")
        self.日志("==========")

        异常退出 = False
        正常完成 = False

        try:
            for i, 行 in enumerate(坐标列表):
                if self.停止标志:
                    self.日志("[*] 用户中断")
                    break

                self.日志(f"\n========== 第{i + 1}/{len(坐标列表)}个坐标点 ==========")
                try:
                    tx, ty, tz, tp, tw, 动作代码 = self.解析坐标行(行)
                except Exception as e:
                    self.日志(f"[ERROR] 行解析失败: {e}  行='{行}'")
                    continue
                self.日志(f"[目标] 位置=({tx}, {ty}, {tz})  视角=(Pitch={tp}, Yaw={tw})  动作={动作代码}")

                self.移动到目标(tx, ty, tz, 关闭冲刺=(关闭shift == 1))
                if self.停止标志: break
                suodi.main(5)
                self.转动视角(tp, tw)
                if self.停止标志: break
                self.日志(f"[动作] 当前行动作代码 = {动作代码}")
                self.执行动作(动作代码)

                self.日志(f"========== 第{i + 1}个坐标点结束 ==========")
            else:
                正常完成 = True
        except 移动超时异常 as e:
            self.日志(f"[超时异常] {e}")
            异常退出 = True
        except Exception as e:
            self.日志(f"[异常] 主循环出错: {type(e).__name__}: {e}")
            异常退出 = True
        finally:
            按键松开(VK_W)

        if self.停止标志:
            self.日志("\n========== 路线被用户中断 ==========")
        elif 异常退出:
            self.日志("\n========== 前面循环异常退出，后续坐标未执行 ==========")
        elif 正常完成:
            self.日志("\n========== 前面坐标全部正常跑完 ==========")
        else:
            self.日志("\n========== 路线执行完毕 ==========")
        ace = False
        return True


# ============================================================
#                     PyQt5 全局样式表
#       （与 console_pyqt5.py 保持一致：深色渐变 + 青调）
# ============================================================
GLOBAL_STYLE = """
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1a1a2e, stop:0.5 #16213e, stop:1 #0f3460);
}
QWidget#loginPage, QWidget#registerPage, QWidget#mainPage {
    background: transparent;
}
QLabel {
    color: #e0e0e0;
    font-family: "Microsoft YaHei";
}
QLabel#titleLabel {
    font-size: 28px;
    font-weight: bold;
    color: #00d2ff;
}
QLabel#subtitleLabel {
    font-size: 13px;
    color: #8892b0;
}
QLineEdit {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 14px;
    color: #ffffff;
    font-family: "Microsoft YaHei";
}
QLineEdit:focus {
    border: 1px solid #00d2ff;
    background: rgba(255, 255, 255, 0.12);
}
QPushButton {
    font-family: "Microsoft YaHei";
    font-size: 14px;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: bold;
}
QPushButton#btnLogin {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d2ff, stop:1 #3a7bd5);
    color: #ffffff;
    border: none;
    font-size: 15px;
    padding: 12px 40px;
}
QPushButton#btnLogin:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00e5ff, stop:1 #4a8be5);
}
QPushButton#btnRegister {
    background: transparent;
    color: #00d2ff;
    border: 1px solid #00d2ff;
    padding: 12px 30px;
    font-size: 15px;
}
QPushButton#btnRegister:hover {
    background: rgba(0, 210, 255, 0.1);
}
QPushButton#btnRegSubmit {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #43e97b, stop:1 #38f9d7);
    color: #1a1a2e;
    border: none;
    font-size: 15px;
    padding: 12px 40px;
}
QPushButton#btnRegSubmit:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #53f98b, stop:1 #48ffe7);
}
QPushButton#btnBack {
    background: transparent;
    color: #8892b0;
    border: 1px solid #8892b0;
    padding: 10px 24px;
}
QPushButton#btnBack:hover {
    color: #e0e0e0;
    border-color: #e0e0e0;
}
QPushButton#btnStart {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #43e97b, stop:1 #38f9d7);
    color: #1a1a2e;
    border: none;
    font-size: 15px;
    padding: 12px 40px;
}
QPushButton#btnStart:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #53f98b, stop:1 #48ffe7);
}
QPushButton#btnStart:disabled {
    background: rgba(255,255,255,0.05);
    color: #6c7a8a;
}
QPushButton#btnStop {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff6b6b, stop:1 #ee5a6f);
    color: #ffffff;
    border: none;
    font-size: 15px;
    padding: 12px 40px;
}
QPushButton#btnStop:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff7b7b, stop:1 #fe6a7f);
}
QPushButton#btnStop:disabled {
    background: rgba(255,255,255,0.05);
    color: #6c7a8a;
}
QPushButton#btnAction {
    background: rgba(0, 210, 255, 0.15);
    color: #00d2ff;
    border: 1px solid rgba(0, 210, 255, 0.3);
    padding: 8px 16px;
    font-size: 13px;
}
QPushButton#btnAction:hover {
    background: rgba(0, 210, 255, 0.25);
    border-color: #00d2ff;
}
QGroupBox {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-family: "Microsoft YaHei";
    font-size: 13px;
    color: #8892b0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #00d2ff;
}
QTextEdit {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    color: #8892b0;
    font-family: Consolas, "Microsoft YaHei";
    font-size: 12px;
    padding: 8px;
}
QSpinBox {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 6px;
    padding: 8px;
    color: #ffffff;
    font-size: 14px;
}
QSpinBox:focus {
    border-color: #00d2ff;
}
QDialog {
    background: #1a1a2e;
}
"""


# ============================================================
#               中控客户端 - 封装 HTTP 接口
#   （来自 test_script.py：注册/登录/申请账号/心跳/上报完成）
# ============================================================
class 中控客户端:
    def __init__(self, base_url=BASE_URL, machine_id=DEFAULT_MACHINE):
        self.base_url = base_url
        self.machine_id = machine_id
        self.user = ""
        self.password = ""
        self.已登录 = False

    def 注册(self, user, password):
        try:
            r = requests.post(f"{self.base_url}/register",
                              json={"user": user, "password": password},
                              timeout=5)
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": f"网络错误: {e}"}

    def 登录(self, user, password):
        try:
            r = requests.post(f"{self.base_url}/login",
                              json={"user": user, "password": password},
                              timeout=5)
            data = r.json()
            if data.get("ok"):
                self.user = user
                self.password = password
                self.已登录 = True
            return data
        except Exception as e:
            return {"ok": False, "msg": f"网络错误: {e}"}

    def 申请账号(self):
        try:
            r = requests.post(f"{self.base_url}/fetch_account",
                              json={"user": self.user,
                                    "machine_id": self.machine_id},
                              timeout=5)
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": f"网络错误: {e}"}

    def 心跳(self, account, level, status="运行中"):
        try:
            requests.post(f"{self.base_url}/heartbeat",
                          json={"user": self.user,
                                "machine_id": self.machine_id,
                                "account": account,
                                "level": level,
                                "status": status},
                          timeout=3)
        except Exception:
            pass

    def 上报完成(self, account, level, coins=0, status="已完成"):
        """跳点一局跑完后，回执游戏账号结果给服务器。
        字段与 test_fetch_account.py 的 update_account 一致：
            account / level / coins / status
        """
        try:
            requests.post(f"{self.base_url}/update_account",
                          json={"account": account,
                                "level": level,
                                "coins": coins,
                                "status": status},
                          timeout=5)
            return True
        except Exception:
            return False


# ============================================================
#       信号桥 - 子线程通过 pyqtSignal 通知 UI 主线程
#   注意：QObject 子类名 / pyqtSignal 属性名必须是 ASCII，
#   否则 sip 注册时会触发 UnicodeEncodeError。
# ============================================================
class SignalBridge(QObject):
    log = pyqtSignal(str)
    status = pyqtSignal(str)  # 顶部状态文本
    account = pyqtSignal(str, int, int)  # 账号 / 当前等级 / 目标等级
    finished = pyqtSignal()


# ============================================================
#                等级完成主流程（核心 TODO 框架）
#
#   这是写给用户自己编辑的样例：
#     1. 中控申请账号
#     2. 真实跑级（用户自己接 跑点.主线程 / 跑点.大坝跑图 等）
#     3. 等级达标后上报中控
#     4. 循环下一个账号
# ============================================================
def 等级完成主流程(跑点, 中控, 桥, 停止事件, 跑图测试=False, 不匹配队友=False):
    桥.log.emit("========== 等级完成主流程 启动 ==========")
    桥.log.emit(f"[配置] 不匹配队友 = {不匹配队友}")
    桥.status.emit("运行中")

    # —— 初始化跑点（DLL + 游戏窗口） ——
    if not 跑点.已初始化:
        桥.log.emit("[初始化] 加载 DLL / 定位游戏窗口 ...")
        if not 跑点.初始化():
            桥.log.emit("[初始化] 失败，流程退出")
            桥.status.emit("初始化失败")
            桥.finished.emit()
            # return
        桥.log.emit("[初始化] 成功")

    while not 停止事件.is_set():
        # ============================================================
        # 步骤 1：获取游戏账号
        #   - 跳过中控申请=True  → 本地虚拟账号（不走服务器）
        #   - 跳过中控申请=False → 调 中控.申请账号() → /fetch_account
        #   注意：中控.user 是中控账号，只用来心跳上报设备状态，
        #         不是这里要跑的游戏账号。
        # ============================================================
        if 跳过中控申请:
            account = LOCAL_ACCOUNT
            password = ""
            目标等级 = int(LOCAL_TARGET_LEVEL)
            起始等级 = int(LOCAL_START_LEVEL)
            起始金币 = 0
            桥.log.emit(f"[跳过中控] 本地虚拟游戏账号 {account}")
        else:
            pass

        当前等级 = 0
        #

        # ============================================================
        # 步骤 2：跑级 —— 与 1.08 一致
        #   勾选跑图测试 → 跑点.大坝跑图()
        #   未勾选         → 跑点.主线程("新手路线1.txt")
        # ============================================================

        try:
            if 跑图测试:
                桥.log.emit("[跑图测试] 勾选 → 调用 跑点.大坝跑图()")
                if not 跑点.已初始化:
                    桥.log.emit("[跑图测试] 未初始化，先调用 初始化()")
                    if not 跑点.初始化():
                        桥.log.emit("[跑图测试] 初始化失败，中止")
                        if not 跳过中控申请:
                            中控.心跳("测试", 当前等级, "初始化失败")
                        continue

                跑点.move_game_window()
                跑点.大坝跑图()
            else:
                hwnd = ctypes.windll.user32.FindWindowW("UnrealWindow", None)
                print("类名查找句柄:", hwnd)
                if not hwnd:
                    桥.log.emit("[申请游戏账号] POST /fetch_account ...")
                    data = 中控.申请账号()
                    if not data.get("ok"):
                        桥.log.emit(f"[申请失败] {data.get('msg')}")
                        桥.status.emit("申请账号失败")
                        # 设备还活着，发个心跳告诉中控用的是中控账号
                        中控.心跳("", 0, "申请失败")
                        if 停止事件.wait(5):
                            break
                        continue
                    account = data.get("account")
                    password = data.get("password")
                    起始等级 = int(data.get("level") or 0)
                    起始金币 = int(data.get("coins") or 0)
                    目标等级 = int(data.get("target_level") or 0)
                    目标金币 = int(data.get("target_coins") or 0)
                    目标key = data.get("target_key")

                    桥.log.emit(
                        f"[申请成功] 游戏账号={account}  起始等级={起始等级}  起始金币={起始金币}  目标等级={目标等级}")
                    桥.account.emit(account, 当前等级, 目标等级)
                    桥.log.emit(f"[账号] {account}  等级 {当前等级} → {目标等级}")
                    桥.status.emit(f"跑级中 {account}")
                    中控.心跳(account, 当前等级, "执行中")
                    自动登录账号密码(account, password)

                else:
                    account = "测试"
                    password = "测试"
                    起始金币 = "0"
                    目标等级 = 0
                    目标金币 = 0
                    目标key = None
                桥.log.emit(f"[主线程] 调用 跑点.主线程，传入游戏账号={account}")
                中控.心跳(account, 当前等级, "执行中")
                time.sleep(5)
                是否完成 = 跑点.主线程(游戏账号=account, 游戏密码=password,
                            起始等级=目标等级, 起始金币=目标金币, 不匹配队友=不匹配队友, 目标key=目标key)
        except Exception as e:
            桥.log.emit(f"[跑级异常] {type(e).__name__}: {e}")
            if not 跳过中控申请:
                中控.心跳(account, 当前等级, "异常")
            continue

        if 停止事件.is_set() or 跑点.停止标志:
            中控.心跳(account, 当前等级, "已停止")
            桥.log.emit(f"[中断] 账号 {account} 被用户停止")
            break

        # ============================================================
        # 步骤 3：路线跑完 → 回执服务器（跳过模式不上报）
        #   /update_account 上报的是游戏账号的最终 level / coins
        #   /heartbeat       上报的是设备状态（中控账号维度）
        # ============================================================
        最终等级 = int(getattr(跑点, "最终等级", 当前等级))
        最终金币 = int(getattr(跑点, "最终金币", 0))
        桥.log.emit(f"[完成] account={account} level={最终等级} coins={最终金币}")
        if 跳过中控申请:
            桥.log.emit("[跳过中控] 不调 /update_account 和 /heartbeat")
        else:
            桥.log.emit("[回执] POST /update_account 上报游戏账号结果")
            中控.上报完成(account, 最终等级, 最终金币, 是否完成)
            # 心跳只是设备状态上报，不代表游戏账号结果
            中控.心跳(account, 最终等级, "已完成")
        桥.status.emit(f"{是否完成} {account}")
        time.sleep(5)
    桥.log.emit("========== 等级完成主流程 结束 ==========")
    桥.status.emit("已停止")
    桥.finished.emit()


# ============================================================
#                  PyQt5 主窗口 - 三页面应用
# ============================================================
class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("跑跑 v1.12 - 中控联动版（目标动态完成+封号检测）")
        self.setMinimumSize(640, 720)
        self.resize(640, 720)

        # 业务对象
        self.中控 = 中控客户端()
        self.跑点 = 自动跑点()
        self.桥 = SignalBridge()
        self.停止事件 = threading.Event()
        self.工作线程 = None

        # 信号槽连接
        self.桥.log.connect(self._on_log)
        self.桥.status.connect(self._on_status)
        self.桥.account.connect(self._on_account_changed)
        self.桥.finished.connect(self._on_finished)

        # 多页面
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login_page = self._build_login_page()
        self.register_page = self._build_register_page()
        self.main_page = self._build_main_page()

        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.register_page)
        self.stack.addWidget(self.main_page)

        self.stack.setCurrentWidget(self.login_page)

    # =====================================================
    #   登录页面
    # =====================================================
    def _build_login_page(self):
        page = QWidget()
        page.setObjectName("loginPage")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        container = QFrame()
        container.setFixedSize(380, 400)
        container.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
            }
        """)
        c_layout = QVBoxLayout()
        c_layout.setContentsMargins(40, 36, 40, 36)
        c_layout.setSpacing(16)

        title = QLabel("三角洲跑跑 v1.12")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(title)

        subtitle = QLabel("登录中控账号")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(subtitle)

        c_layout.addSpacing(10)

        self.login_user = QLineEdit()
        self.login_user.setPlaceholderText("请输入账号")
        self.login_user.setFixedHeight(42)
        c_layout.addWidget(self.login_user)

        self.login_pass = QLineEdit()
        self.login_pass.setPlaceholderText("请输入密码")
        self.login_pass.setEchoMode(QLineEdit.Password)
        self.login_pass.setFixedHeight(42)
        c_layout.addWidget(self.login_pass)

        # 回填上一次登录成功的账号密码
        记忆_user, 记忆_pass = 加载登录记忆()
        if 记忆_user:
            self.login_user.setText(记忆_user)
        if 记忆_pass:
            self.login_pass.setText(记忆_pass)

        c_layout.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_login = QPushButton("登 录")
        btn_login.setObjectName("btnLogin")
        btn_login.clicked.connect(self.do_login)
        btn_row.addWidget(btn_login)

        btn_reg = QPushButton("注 册")
        btn_reg.setObjectName("btnRegister")
        btn_reg.clicked.connect(lambda: self.stack.setCurrentWidget(self.register_page))
        btn_row.addWidget(btn_reg)
        c_layout.addLayout(btn_row)

        container.setLayout(c_layout)
        layout.addWidget(container)
        page.setLayout(layout)
        return page

    # =====================================================
    #   注册页面
    # =====================================================
    def _build_register_page(self):
        page = QWidget()
        page.setObjectName("registerPage")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        container = QFrame()
        container.setFixedSize(380, 440)
        container.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
            }
        """)
        c_layout = QVBoxLayout()
        c_layout.setContentsMargins(40, 36, 40, 36)
        c_layout.setSpacing(16)

        title = QLabel("注册新账号")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(title)

        subtitle = QLabel("创建一个脚本登录账号")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(subtitle)

        c_layout.addSpacing(10)

        self.reg_user = QLineEdit()
        self.reg_user.setPlaceholderText("设置账号")
        self.reg_user.setFixedHeight(42)
        c_layout.addWidget(self.reg_user)

        self.reg_pass = QLineEdit()
        self.reg_pass.setPlaceholderText("设置密码")
        self.reg_pass.setEchoMode(QLineEdit.Password)
        self.reg_pass.setFixedHeight(42)
        c_layout.addWidget(self.reg_pass)

        self.reg_pass2 = QLineEdit()
        self.reg_pass2.setPlaceholderText("确认密码")
        self.reg_pass2.setEchoMode(QLineEdit.Password)
        self.reg_pass2.setFixedHeight(42)
        c_layout.addWidget(self.reg_pass2)

        c_layout.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_submit = QPushButton("注 册")
        btn_submit.setObjectName("btnRegSubmit")
        btn_submit.clicked.connect(self.do_register)
        btn_row.addWidget(btn_submit)

        btn_back = QPushButton("返回登录")
        btn_back.setObjectName("btnBack")
        btn_back.clicked.connect(lambda: self.stack.setCurrentWidget(self.login_page))
        btn_row.addWidget(btn_back)
        c_layout.addLayout(btn_row)

        container.setLayout(c_layout)
        layout.addWidget(container)
        page.setLayout(layout)
        return page

    # =====================================================
    #   主页面（启动/停止 + 状态 + 日志）
    # =====================================================
    def _build_main_page(self):
        page = QWidget()
        page.setObjectName("mainPage")
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(16, 12, 16, 12)

        # 顶部栏
        top_bar = QHBoxLayout()
        self.lbl_welcome = QLabel("欢迎")
        self.lbl_welcome.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.lbl_welcome.setStyleSheet("color: #00d2ff;")
        top_bar.addWidget(self.lbl_welcome)
        top_bar.addStretch()

        btn_logout = QPushButton("退出登录")
        btn_logout.setObjectName("btnBack")
        btn_logout.clicked.connect(self.do_logout)
        top_bar.addWidget(btn_logout)
        main_layout.addLayout(top_bar)

        # 状态信息区
        info_group = QGroupBox("运行状态")
        info_lay = QVBoxLayout()
        self.lbl_status = QLabel("状态：未启动")
        self.lbl_status.setFont(QFont("Microsoft YaHei", 11))
        self.lbl_status.setStyleSheet("color: #e0e0e0; padding: 4px 0;")
        info_lay.addWidget(self.lbl_status)

        self.lbl_account = QLabel("账号：-      等级：- / -")
        self.lbl_account.setFont(QFont("Microsoft YaHei", 10))
        self.lbl_account.setStyleSheet("color: #8892b0; padding: 4px 0;")
        info_lay.addWidget(self.lbl_account)
        info_group.setLayout(info_lay)
        main_layout.addWidget(info_group)

        # 运行参数
        cfg_group = QGroupBox("运行参数")
        cfg_lay = QHBoxLayout()
        cfg_lay.addWidget(QLabel("机器号："))
        self.spin_machine = QSpinBox()
        self.spin_machine.setRange(1, 999)
        self.spin_machine.setValue(int(DEFAULT_MACHINE) if str(DEFAULT_MACHINE).isdigit() else 1)
        cfg_lay.addWidget(self.spin_machine)
        cfg_lay.addSpacing(20)

        # 跑图测试勾选框（与 1.08 一致）— 勾选后启动直接调 跑点.大坝跑图()
        self.chk_test = QCheckBox("跑图测试")
        self.chk_test.setChecked(False)
        self.chk_test.setStyleSheet("color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 13px;")
        cfg_lay.addWidget(self.chk_test)

        # 不匹配队友勾选框
        self.chk_no_match = QCheckBox("不匹配队友")
        self.chk_no_match.setChecked(False)
        self.chk_no_match.setStyleSheet("color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 13px;")
        cfg_lay.addWidget(self.chk_no_match)

        # 验证码Key 输入框
        key_label = QLabel("验证码Key:")
        key_label.setStyleSheet("color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 13px;")
        cfg_lay.addWidget(key_label)
        self.edit_keycode = QLineEdit(验证码Key)
        self.edit_keycode.setStyleSheet("color: #e0e0e0; font-family: 'Microsoft YaHei'; font-size: 13px; background: #16213e; border: 1px solid #555; padding: 4px;")
        self.edit_keycode.setFixedWidth(160)
        cfg_lay.addWidget(self.edit_keycode)

        cfg_lay.addStretch()
        cfg_group.setLayout(cfg_lay)
        main_layout.addWidget(cfg_group)

        # 启动/停止
        ctrl_group = QGroupBox("控制")
        ctrl_lay = QHBoxLayout()
        self.btn_start = QPushButton("▶  启动任务")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self.start_run)
        ctrl_lay.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■  停止任务")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.clicked.connect(self.stop_run)
        self.btn_stop.setEnabled(False)
        ctrl_lay.addWidget(self.btn_stop)
        ctrl_group.setLayout(ctrl_lay)
        main_layout.addWidget(ctrl_group)

        # 日志
        log_group = QGroupBox("运行日志")
        log_lay = QVBoxLayout()
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(260)
        log_lay.addWidget(self.txt_log)
        log_group.setLayout(log_lay)
        main_layout.addWidget(log_group, 1)

        page.setLayout(main_layout)
        return page

    # =====================================================
    #   登录 / 注册 / 退出
    # =====================================================
    def do_login(self):
        user = self.login_user.text().strip()
        password = self.login_pass.text().strip()
        if not user or not password:
            QMessageBox.warning(self, "提示", "请输入账号和密码")
            return
        data = self.中控.登录(user, password)
        if data.get("ok"):
            保存登录记忆(user, password)
            self.lbl_welcome.setText(f"欢迎，{user}")
            self.stack.setCurrentWidget(self.main_page)
            self._on_log(f"[登录] 成功：{user}")
        else:
            QMessageBox.warning(self, "登录失败", data.get("msg", "未知错误"))

    def do_register(self):
        user = self.reg_user.text().strip()
        p1 = self.reg_pass.text().strip()
        p2 = self.reg_pass2.text().strip()
        if not user or not p1:
            QMessageBox.warning(self, "提示", "请输入账号和密码")
            return
        if p1 != p2:
            QMessageBox.warning(self, "提示", "两次密码不一致")
            return
        data = self.中控.注册(user, p1)
        if data.get("ok"):
            QMessageBox.information(self, "成功", "注册成功，请登录")
            self.login_user.setText(user)
            self.login_pass.setText(p1)
            self.stack.setCurrentWidget(self.login_page)
        else:
            QMessageBox.warning(self, "注册失败", data.get("msg", "未知错误"))

    def do_logout(self):
        if self.工作线程 is not None and self.工作线程.is_alive():
            QMessageBox.warning(self, "提示", "请先停止任务")
            return
        self.中控.已登录 = False
        self.stack.setCurrentWidget(self.login_page)

    # =====================================================
    #   启动 / 停止
    # =====================================================
    def start_run(self):
        if self.工作线程 is not None and self.工作线程.is_alive():
            return
        # 同步机器号
        self.中控.machine_id = str(self.spin_machine.value())
        跑图测试 = self.chk_test.isChecked()
        不匹配队友 = self.chk_no_match.isChecked()
        # 同步验证码Key 到全局变量
        global 验证码Key
        验证码Key = self.edit_keycode.text().strip() or 验证码Key

        self.停止事件.clear()
        self.跑点.停止标志 = False
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.txt_log.clear()
        self._on_log(f"[启动] 准备进入主流程 ... 跑图测试={跑图测试}  不匹配队友={不匹配队友}")

        self.工作线程 = threading.Thread(
            target=等级完成主流程,
            args=(self.跑点, self.中控, self.桥, self.停止事件, 跑图测试, 不匹配队友),
            daemon=True,
        )
        self.工作线程.start()

    def stop_run(self):
        self._on_log("[停止] 发送停止信号中 ...")
        self.停止事件.set()
        self.跑点.请求停止()
        self.btn_stop.setEnabled(False)

    # =====================================================
    #   信号槽
    # =====================================================
    def _on_log(self, text):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{ts}] {text}")

    def _on_status(self, status):
        self.lbl_status.setText(f"状态：{status}")

    def _on_account_changed(self, account, level, target):
        self.lbl_account.setText(f"账号：{account}      等级：{level} / {target}")

    def _on_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._on_log("[结束] 主流程已退出")

    # =====================================================
    #   关窗清理
    # =====================================================
    def closeEvent(self, event):
        try:
            self.停止事件.set()
            self.跑点.请求停止()
            if self.工作线程 is not None and self.工作线程.is_alive():
                self.工作线程.join(timeout=2)
            self.跑点.关闭()
        except Exception:
            pass
        event.accept()


# ============================================================
#                          入口
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLE)
    w = MainApp()
    w.show()
    sys.exit(app.exec_())
