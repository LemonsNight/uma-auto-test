"""探测现代记事本是否能用 RichEditD2DPT 子窗口验证真实点击。

只用 SendMessage 做测试前后的文本/插入符读取，
点击仍然只用 PostMessage（与被测实现一致）。
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

WM_SETTEXT = 0x000C
EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


def find_notepad() -> int:
    found = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "Notepad":
            found.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return found[-1] if found else 0


def find_child(hwnd: int, cls: str) -> int:
    result = []

    def cb(h, acc):
        if win32gui.GetClassName(h) == cls:
            acc.append(h)
        return True

    win32gui.EnumChildWindows(hwnd, cb, result)
    return result[0] if result else 0


def get_sel(hwnd: int) -> tuple[int, int]:
    value = win32gui.SendMessage(hwnd, EM_GETSEL, 0, 0)
    return value & 0xFFFF, (value >> 16) & 0xFFFF


def main() -> None:
    if not find_notepad():
        subprocess.Popen([r"C:\Windows\System32\notepad.exe"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    root = find_notepad()
    win32gui.ShowWindow(root, win32con.SW_RESTORE)
    win32gui.BringWindowToTop(root)
    try:
        win32gui.SetForegroundWindow(root)
    except Exception as exc:
        print("SetForegroundWindow 提示:", exc)
    time.sleep(0.6)
    print(f"前台窗口=0x{int(user32.GetForegroundWindow()):X}")
    print(f"Notepad root HWND=0x{root:X} title={win32gui.GetWindowText(root)!r}")
    for cls in ("NotepadTextBox", "RichEditD2DPT"):
        print(f"  {cls}: 0x{find_child(root, cls):X}")

    edit = find_child(root, "RichEditD2DPT")
    if not edit:
        print("未找到 RichEditD2DPT，无法用插入符验证")
        return

    text = "AAAAAAAAAAAAAAAAAAAA\nBBBBBBBBBBBBBBBBBBBB\nCCCCCCCCCCCCCCCCCCCC"
    sent = win32gui.SendMessage(edit, WM_SETTEXT, 0, text)
    print(f"WM_SETTEXT -> {sent}, text={win32gui.SendMessage(edit, 0x000D, 0, 0)!r}")
    win32gui.SendMessage(edit, EM_SETSEL, 0, 0)
    print("插入符(初始):", get_sel(edit))

    rect = win32gui.GetWindowRect(edit)
    print(f"RichEdit rect={rect}")
    point = (rect[0] + 240, rect[1] + 60)
    hit = int(user32.WindowFromPoint(wintypes.POINT(*point)))
    print(f"点击点 {point} -> WindowFromPoint 0x{hit:X} class={win32gui.GetClassName(hit)!r}")

    # 使用该命中窗口自己的客户区坐标
    cx, cy = win32gui.ScreenToClient(hit, point)
    lparam = (cx & 0xFFFF) | ((cy & 0xFFFF) << 16)
    for msg, wp in ((WM_MOUSEMOVE, 0), (WM_LBUTTONDOWN, MK_LBUTTON), (WM_LBUTTONUP, 0)):
        ok = bool(user32.PostMessageW(wintypes.HWND(hit), wintypes.UINT(msg),
                                     wintypes.WPARAM(wp), wintypes.LPARAM(lparam)))
        print(f"  {msg:#06x} posted={ok}")

    time.sleep(0.5)
    print("插入符(点击后):", get_sel(edit))
    print("结论: 若插入符从 (0,0) 变化，则 PostMessage 点击被记事本真实处理")


if __name__ == "__main__":
    main()
