"""截图工具：用 Win32 BitBlt 抓取整个虚拟屏幕并保存为 PNG。

不依赖 PIL；通过 Qt QImage 把 BMP 转成 PNG。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import win32api
import win32con
import win32gui
import win32ui

from PySide6 import QtGui


def capture_virtual_screen(output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

    desktop = win32gui.GetDesktopWindow()
    desktop_dc = win32gui.GetWindowDC(desktop)
    src_dc = win32ui.CreateDCFromHandle(desktop_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(src_dc, width, height)
    mem_dc.SelectObject(bitmap)
    mem_dc.BitBlt((0, 0), (width, height), src_dc, (left, top), win32con.SRCCOPY)

    fd, tmp_bmp = tempfile.mkstemp(suffix=".bmp")
    os.close(fd)
    try:
        bitmap.SaveBitmapFile(mem_dc, tmp_bmp)
        image = QtGui.QImage(tmp_bmp)
        if image.isNull():
            raise RuntimeError("读取临时 BMP 失败")
        if not image.save(str(output_path), "PNG"):
            raise RuntimeError(f"保存 PNG 失败: {output_path}")
    finally:
        try:
            os.remove(tmp_bmp)
        except OSError:
            pass
        mem_dc.DeleteDC()
        src_dc.DeleteDC()
        win32gui.ReleaseDC(desktop, desktop_dc)

    return output_path
