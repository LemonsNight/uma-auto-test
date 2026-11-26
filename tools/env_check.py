"""环境诊断脚本：输出 Python / Windows / DPI / 显示器信息。

用法：
    python tools/env_check.py

只读脚本，不修改系统设置（除了将本进程标记为 Per-Monitor DPI Aware，
仅影响本进程，用于读取真实物理坐标）。
"""

from __future__ import annotations

import ctypes
import platform
import sys

# 必须在任何窗口/坐标 API 之前设置进程 DPI 感知，否则多显示器坐标会被虚拟化。
_PROCESS_PER_MONITOR_DPI_AWARE = 2
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(_PROCESS_PER_MONITOR_DPI_AWARE)
    _dpi_note = "SetProcessDpiAwareness(PER_MONITOR_DPI_AWARE) 成功"
except Exception as exc:  # pragma: no cover - 老系统可能没有 shcore
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        _dpi_note = f"shcore 不可用({exc})，回退 SetProcessDPIAware()"
    except Exception as exc2:  # pragma: no cover
        _dpi_note = f"设置 DPI 感知失败: {exc} / {exc2}"


def _registry_display_version() -> str:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        )
        values = {}
        for name in ("ProductName", "DisplayVersion", "CurrentBuild", "UBR"):
            try:
                values[name] = winreg.QueryValueEx(key, name)[0]
            except OSError:
                values[name] = "?"
        winreg.CloseKey(key)
        return (
            f"{values['ProductName']} {values['DisplayVersion']} "
            f"(build {values['CurrentBuild']}.{values['UBR']})"
        )
    except Exception as exc:  # pragma: no cover
        return f"读取注册表失败: {exc}"


def main() -> None:
    print("=" * 64)
    print("VirtualMouse Phase 1 - 环境诊断")
    print("=" * 64)
    print(f"Python 可执行文件 : {sys.executable}")
    print(f"Python 版本       : {sys.version}")
    print(f"platform.platform : {platform.platform()}")
    print(f"platform.win32_ver: {platform.win32_ver()}")
    print(f"Windows (注册表)  : {_registry_display_version()}")
    print(f"DPI 感知设置      : {_dpi_note}")

    try:
        import PySide6
        from PySide6 import QtCore

        print(f"PySide6           : {PySide6.__version__}")
        print(f"Qt runtime        : {QtCore.qVersion()}")
    except Exception as exc:
        print(f"PySide6           : 不可用 ({exc})")

    try:
        import win32api
        import win32con

        print("pywin32           : 可用")
        sm = win32con
        for name in (
            "SM_CXSCREEN",
            "SM_CYSCREEN",
            "SM_XVIRTUALSCREEN",
            "SM_YVIRTUALSCREEN",
            "SM_CXVIRTUALSCREEN",
            "SM_CYVIRTUALSCREEN",
            "SM_CMONITORS",
        ):
            print(f"{name:<21}: {win32api.GetSystemMetrics(getattr(sm, name))}")

        monitors = win32api.EnumDisplayMonitors()
        print(f"\n显示器数量 (EnumDisplayMonitors): {len(monitors)}")
        for i, monitor in enumerate(monitors):
            hwnd, hdc, rect = monitor
            info = win32api.GetMonitorInfo(hwnd)
            print(f"  [{i}] handle={hwnd}")
            print(f"      monitor rect = {tuple(rect)}")
            print(f"      work    rect = {tuple(info['Work'])}")
            print(f"      device name  = {info['Device']}")
            print(f"      primary      = {bool(info['Flags'] & 1)}")

        print("\n各显示器 DPI:")
        for i, monitor in enumerate(monitors):
            try:
                hmon = monitor[0]
                hdc = ctypes.windll.user32.GetDC(None)
                # 先切换到目标显示器的 DC 上下文不适用；改用 per-monitor API
                dpi_x = ctypes.c_uint()
                dpi_y = ctypes.c_uint()
                hr = ctypes.windll.shcore.GetDpiForMonitor(
                    int(hmon), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
                )
                ctypes.windll.user32.ReleaseDC(None, hdc)
                if hr == 0:
                    print(
                        f"  [{i}] DPI = ({dpi_x.value}, {dpi_y.value})  "
                        f"缩放 ≈ {dpi_x.value / 96 * 100:.0f}%"
                    )
                else:
                    print(f"  [{i}] GetDpiForMonitor 失败 HRESULT={hr}")
            except Exception as exc:
                print(f"  [{i}] 读取 DPI 失败: {exc}")
    except Exception as exc:
        print(f"pywin32           : 不可用 ({exc})")

    print("=" * 64)


if __name__ == "__main__":
    main()
