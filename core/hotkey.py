"""全局紧急停止快捷键（RegisterHotKey + Qt 原生事件过滤器）。

只注册一个不常用的三键组合，不劫持普通按键，不影响用户正常使用其它软件。
注册失败时会明确报告，不静默降级为其它输入方式。
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from PySide6 import QtCore

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [
    wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.PostMessageW.restype = wintypes.BOOL

WM_HOTKEY = 0x0312


class _HotkeyNativeFilter(QtCore.QAbstractNativeEventFilter):
    """把 WM_HOTKEY 转成 Qt 信号。"""

    def __init__(self, owner: "GlobalHotkey") -> None:
        super().__init__()
        self._owner = owner
        self._last_trigger = 0.0

    def nativeEventFilter(self, eventType, message):
        try:
            if bytes(eventType) == b"windows_generic_MSG":
                msg = ctypes.cast(
                    int(message), ctypes.POINTER(wintypes.MSG)
                ).contents
                if msg.message == WM_HOTKEY and int(msg.wParam) == self._owner.hotkey_id:
                    # 同一条 WM_HOTKEY 可能经 Qt 多次投递到过滤器，做短去重。
                    now = time.monotonic()
                    if now - self._last_trigger > 0.15:
                        self._last_trigger = now
                        self._owner.triggered.emit()
        except Exception as exc:  # 绝不因过滤器异常影响主循环
            logger.debug("原生事件过滤异常: %s", exc)
        return False, 0


class GlobalHotkey(QtCore.QObject):
    """注册并接收全局热键。"""

    triggered = QtCore.Signal()
    registration_failed = QtCore.Signal(str)

    def __init__(
        self,
        target_hwnd_provider,
        modifiers: int,
        vk: int,
        label: str,
        hotkey_id: int = 1,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._hwnd_provider = target_hwnd_provider
        self.modifiers = modifiers
        self.vk = vk
        self.label = label
        self.hotkey_id = hotkey_id
        self._filter = _HotkeyNativeFilter(self)
        self._registered = False
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self) -> bool:
        hwnd = int(self._hwnd_provider())
        if not hwnd:
            self._fail("目标窗口尚无 HWND，无法注册热键")
            return False
        ctypes.set_last_error(0)
        ok = bool(user32.RegisterHotKey(hwnd, self.hotkey_id, self.modifiers, self.vk))
        if not ok:
            err = ctypes.get_last_error()
            self._fail(f"RegisterHotKey 失败 GetLastError={err}（组合键可能已被占用）")
            return False
        self._registered = True
        logger.info("全局紧急停止热键已注册: %s", self.label)
        return True

    def unregister(self) -> None:
        if not self._registered:
            return
        hwnd = int(self._hwnd_provider())
        if hwnd:
            user32.UnregisterHotKey(wintypes.HWND(hwnd), self.hotkey_id)
        self._registered = False
        logger.info("全局热键已注销")

    def simulate_for_test(self) -> bool:
        """仅用于测试：向目标窗口投递 WM_HOTKEY 验证处理链路。"""
        hwnd = int(self._hwnd_provider())
        if not hwnd:
            return False
        return bool(
            user32.PostMessageW(
                wintypes.HWND(hwnd),
                wintypes.UINT(WM_HOTKEY),
                wintypes.WPARAM(self.hotkey_id),
                wintypes.LPARAM(0),
            )
        )

    def _fail(self, message: str) -> None:
        logger.warning(message)
        self.registration_failed.emit(message)
