"""虚拟光标控制器：状态机 + 输入编排。

GUI 只调用此类的方法与信号，不直接触碰 Win32 输入 API。
"""

from __future__ import annotations

import logging
from enum import Enum

from PySide6 import QtCore

from config import settings
from .coordinate import DesktopCoordinate
from .input_backend import ClickResult, PostMessageBackend
from .window_resolver import ResolvedTarget, WindowResolver

logger = logging.getLogger(__name__)


class CursorState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class VirtualCursorController(QtCore.QObject):
    """协调 Overlay、窗口解析与 PostMessage 后端。"""

    state_changed = QtCore.Signal(str)
    log_emitted = QtCore.Signal(str)
    moved = QtCore.Signal(int, int)
    click_feedback = QtCore.Signal()
    click_finished = QtCore.Signal(object)

    def __init__(
        self,
        overlay,
        resolver: WindowResolver,
        backend: PostMessageBackend,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.overlay = overlay
        self.resolver = resolver
        self.backend = backend
        self._state = CursorState.IDLE
        self._last_click: ClickResult | None = None

    @property
    def state(self) -> CursorState:
        return self._state

    @property
    def last_click(self) -> ClickResult | None:
        return self._last_click

    # ---------- 状态机 ----------
    def start(self) -> None:
        if self._state in (CursorState.RUNNING, CursorState.PAUSED):
            self._log("已在运行，忽略重复启动")
            return
        if self._state is CursorState.STOPPED:
            self._log("处于紧急停止状态，请先复位", logging.WARNING)
            return
        self._set_state(CursorState.RUNNING)
        self._log("控制器已启动")

    def pause(self) -> None:
        if self._state is not CursorState.RUNNING:
            self._log(f"当前状态 {self._state.value}，无需暂停", logging.WARNING)
            return
        self._set_state(CursorState.PAUSED)
        self._log("已暂停：后续点击将被拒绝，圆点仍可手动移动")

    def resume(self) -> None:
        if self._state is not CursorState.PAUSED:
            self._log(f"当前状态 {self._state.value}，无法恢复", logging.WARNING)
            return
        self._set_state(CursorState.RUNNING)
        self._log("已恢复运行")

    def emergency_stop(self, reason: str = "用户触发紧急停止") -> None:
        """立即停止：之后所有点击都被拒绝，直到显式复位。"""
        previous = self._state.value
        self._set_state(CursorState.STOPPED)
        self._log(f"[{reason}] 紧急停止：状态 {previous} -> stopped，后续操作全部拒绝",
                  logging.CRITICAL)

    def reset(self) -> None:
        """紧急停止后显式复位到运行中。"""
        if self._state is not CursorState.STOPPED:
            self._log(f"当前状态 {self._state.value}，无需复位", logging.WARNING)
            return
        self._set_state(CursorState.RUNNING)
        self._log("已复位，恢复运行")

    def _set_state(self, state: CursorState) -> None:
        self._state = state
        self.state_changed.emit(state.value)

    # ---------- 操作 ----------
    def move_to(self, coord: DesktopCoordinate) -> bool:
        if self._state is CursorState.STOPPED:
            self._log("紧急停止中，拒绝移动", logging.WARNING)
            return False
        ok = self.overlay.move_to_desktop(coord)
        if ok:
            self._log(f"圆点移动到桌面坐标 {coord}")
            self.moved.emit(coord.x, coord.y)
        else:
            self._log(f"圆点移动失败：无法定位 {coord}", logging.ERROR)
        return ok

    def click_at(self, coord: DesktopCoordinate) -> ClickResult | None:
        if self._state is CursorState.STOPPED:
            self._log("紧急停止中，拒绝点击", logging.WARNING)
            return None
        if self._state is CursorState.PAUSED:
            self._log("已暂停，拒绝点击", logging.WARNING)
            return None
        if self._state is CursorState.IDLE:
            self.start()

        self._log(f"开始点击流程，桌面坐标 {coord}")
        target: ResolvedTarget = self.resolver.resolve(coord)
        if not target.is_safe_target:
            self._log(f"点击取消：{target.reject_reason}", logging.WARNING)
            # 仍然给出结果对象，方便 UI 与报告记录拒绝原因。
            from .input_backend import ClickResult  # 局部导入避免循环
            result = ClickResult(coord=coord, target=target)
            result.errors.append(f"目标被拒绝: {target.reject_reason}")
            self._last_click = result
            self.click_finished.emit(result)
            return result

        result = self.backend.click(coord, target)
        self._last_click = result
        # 视觉反馈只代表"发起了一次点击"，不代表点击被目标处理。
        self.click_feedback.emit()
        for line in result.describe().splitlines():
            self._log(line)
        self.click_finished.emit(result)
        return result

    def set_overlay_visible(self, visible: bool) -> None:
        self.overlay.set_overlay_visible(visible)
        self._log("显示圆点" if visible else "隐藏圆点")

    # ---------- 日志 ----------
    def _log(self, message: str, level: int = logging.INFO) -> None:
        logger.log(level, message)
        self.log_emitted.emit(message)
