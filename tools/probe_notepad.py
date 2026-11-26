"""探测本机 Notepad 实现与可验证性（只读 + 启动记事本）。

输出：
- notepad.exe 路径与版本
- 顶层窗口 HWND / 类名 / 标题
- 子窗口树与类名
- 是否存在经典 Edit 控件（可用 EM_GETSEL 验证点击）
"""

from __future__ import annotations

import subprocess
import time

import win32api
import win32gui
import win32process


def find_notepad_windows():
    found = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if "Notepad" in title or "记事本" in title or "Untitled" in title:
            found.append((hwnd, cls, title, pid))
        elif cls in ("Edit", "RichEdit20W", "RichEdit50W"):
            parent = win32gui.GetAncestor(hwnd, 2)
            if "Notepad" in win32gui.GetWindowText(parent) or "记事本" in win32gui.GetWindowText(parent):
                found.append((hwnd, cls, title, pid))

    win32gui.EnumWindows(callback, None)
    return found


def dump_children(hwnd: int, depth: int = 0, max_depth: int = 3) -> None:
    if depth > max_depth:
        return
    children: list[int] = []

    def collect(h, acc):
        acc.append(h)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, collect, children)
    except Exception:
        return
    for child in children[:30]:
        try:
            cls = win32gui.GetClassName(child)
            text = win32gui.GetWindowText(child)[:60]
            rect = win32gui.GetWindowRect(child)
            print(f"  {'  ' * depth}child HWND=0x{child:X} class={cls!r} text={text!r} rect={rect}")
        except Exception as exc:
            print(f"  {'  ' * depth}child error {exc}")


def main() -> None:
    path = r"C:\Windows\System32\notepad.exe"
    try:
        info = win32api.GetFileVersionInfo(path, "\\")
        print("notepad.exe 版本:",
              f"{info['FileVersionMS'] >> 16}.{info['FileVersionMS'] & 0xFFFF}."
              f"{info['FileVersionLS'] >> 16}.{info['FileVersionLS'] & 0xFFFF}")
    except Exception as exc:
        print("读取版本失败:", exc)

    print("启动前窗口:", find_notepad_windows())
    subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)

    windows = find_notepad_windows()
    print(f"启动后找到 {len(windows)} 个相关窗口:")
    for hwnd, cls, title, pid in windows:
        print(f"  HWND=0x{hwnd:X} class={cls!r} title={title!r} pid={pid} rect={win32gui.GetWindowRect(hwnd)}")
        dump_children(hwnd)


if __name__ == "__main__":
    main()
