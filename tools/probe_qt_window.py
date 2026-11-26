"""探测 Qt 6 / Windows 11 下透明叠加窗口的真实行为（不是只看 API 名字）。

检查：
1. WindowTransparentForInput 是否真的使 WS_EX_TRANSPARENT 生效；
2. WindowDoesNotAcceptFocus / Tool 是否使 WS_EX_NOACTIVATE 生效；
3. Qt move() 在混合 DPI 多显示器下是否使用物理像素；
4. WindowFromPoint 是否会穿透叠加窗口命中下层窗口。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6 import QtCore, QtWidgets

import win32api
import win32con
import win32gui

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080

user32 = ctypes.windll.user32
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND


def set_dpi_awareness() -> None:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE


def exstyle_of(hwnd: int) -> int:
    return ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)


def rect_of(hwnd: int):
    r = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def hwnd_title(hwnd: int) -> str:
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return "<invalid>"


def main() -> int:
    set_dpi_awareness()
    app = QtWidgets.QApplication(sys.argv)

    w = QtWidgets.QWidget()
    w.setWindowFlags(
        QtCore.Qt.WindowType.FramelessWindowHint
        | QtCore.Qt.WindowType.WindowStaysOnTopHint
        | QtCore.Qt.WindowType.WindowTransparentForInput
        | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
        | QtCore.Qt.WindowType.Tool
    )
    w.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    w.setFixedSize(40, 40)
    w.setWindowTitle("VM_PROBE_OVERLAY")
    w.show()
    QtWidgets.QApplication.processEvents()

    hwnd = int(w.winId())
    print("=== 窗口标志实际验证 ===")
    ex = exstyle_of(hwnd)
    print(f"HWND = {hwnd}")
    print(f"EXSTYLE = 0x{ex:08X}")
    for name, bit in (
        ("WS_EX_TRANSPARENT", WS_EX_TRANSPARENT),
        ("WS_EX_NOACTIVATE", WS_EX_NOACTIVATE),
        ("WS_EX_LAYERED", WS_EX_LAYERED),
        ("WS_EX_TOOLWINDOW", WS_EX_TOOLWINDOW),
    ):
        print(f"  {name:<20}: {'ON' if ex & bit else 'OFF'}")

    print("\n=== Qt move() 在混合 DPI 下的坐标映射 ===")
    for target in ((300, 300), (3000, 100), (3000, -40)):
        w.move(target[0], target[1])
        QtWidgets.QApplication.processEvents()
        r = rect_of(hwnd)
        print(
            f"  move{target} -> GetWindowRect {r} "
            f"(期望左上角 = {target})"
        )

    print("\n=== Win32 SetWindowPos 物理坐标映射 ===")
    for target in ((300, 300), (3000, 100), (3000, -40)):
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            target[0],
            target[1],
            40,
            40,
            0x0004 | 0x0010,  # NOACTIVATE | NOZORDER
        )
        QtWidgets.QApplication.processEvents()
        r = rect_of(hwnd)
        print(f"  SetWindowPos{target} -> GetWindowRect {r}")

    print("\n=== WindowFromPoint 是否穿透叠加窗口 ===")
    for point in ((320, 320), (3020, 120)):
        r = rect_of(hwnd)
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            point[0],
            point[1],
            40,
            40,
            0x0004 | 0x0010,
        )
        QtWidgets.QApplication.processEvents()
        hit = int(user32.WindowFromPoint(wintypes.POINT(point[0] + 5, point[1] + 5)))
        print(
            f"  点 ({point[0]+5},{point[1]+5}) 叠加窗口 rect={r} -> "
            f"命中 HWND={hit} title={hwnd_title(hit)!r} "
            f"{'== 自身(未穿透!)' if hit == hwnd else '!= 自身(穿透 OK)'}"
        )

    print("\n=== 真实鼠标位置是否被改变 ===")
    before = win32api.GetCursorPos()
    w.move(100, 100)
    user32.SetWindowPos(wintypes.HWND(hwnd), None, 200, 200, 40, 40, 0x0004)
    QtWidgets.QApplication.processEvents()
    after = win32api.GetCursorPos()
    print(f"  before={before} after={after} {'OK' if before == after else 'FAIL'}")

    w.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
