"""控制面板：X/Y 坐标、移动、单击、显示隐藏、暂停恢复、紧急停止、状态与日志。

本文件不直接调用任何 Win32 输入 API；所有操作通过 VirtualCursorController。
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from config import settings
from core.coordinate import DesktopCoordinate
from core.virtual_cursor import VirtualCursorController


class MainWindow(QtWidgets.QWidget):
    def __init__(
        self,
        controller: VirtualCursorController,
        hotkey_label: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("VirtualMouse Phase 1 - 控制面板")
        self.setMinimumWidth(520)

        self._build_ui(hotkey_label)
        self._connect_signals()
        self._sync_state(controller.state.value)
        self._append_log("控制面板已就绪。圆点已显示，可在下方输入桌面坐标。")
        self._append_log(
            "说明：消息入队成功 ≠ 目标程序已处理点击；实际点击需外部证据验证。"
        )

    def _build_ui(self, hotkey_label: str) -> None:
        root = QtWidgets.QVBoxLayout(self)

        # 状态区
        status_box = QtWidgets.QGroupBox("状态")
        status_layout = QtWidgets.QFormLayout(status_box)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.hotkey_label = QtWidgets.QLabel(f"{hotkey_label}（全局紧急停止）")
        status_layout.addRow("当前状态：", self.status_label)
        status_layout.addRow("紧急停止热键：", self.hotkey_label)
        root.addWidget(status_box)

        # 坐标与操作区
        coord_box = QtWidgets.QGroupBox("桌面坐标（物理像素，支持副屏/负数）")
        coord_layout = QtWidgets.QGridLayout(coord_box)
        coord_layout.addWidget(QtWidgets.QLabel("X:"), 0, 0)
        coord_layout.addWidget(QtWidgets.QLabel("Y:"), 0, 2)

        self.x_spin = QtWidgets.QSpinBox()
        self.x_spin.setRange(-10000, 20000)
        self.x_spin.setValue(800)
        self.x_spin.setToolTip("桌面物理 X 坐标")
        self.y_spin = QtWidgets.QSpinBox()
        self.y_spin.setRange(-10000, 20000)
        self.y_spin.setValue(400)
        self.y_spin.setToolTip("桌面物理 Y 坐标")
        coord_layout.addWidget(self.x_spin, 0, 1)
        coord_layout.addWidget(self.y_spin, 0, 3)

        self.move_button = QtWidgets.QPushButton("移动圆点")
        self.click_button = QtWidgets.QPushButton("单击")
        self.visible_button = QtWidgets.QPushButton("隐藏圆点")
        coord_layout.addWidget(self.move_button, 1, 0, 1, 2)
        coord_layout.addWidget(self.click_button, 1, 2, 1, 2)
        root.addWidget(coord_box)

        control_box = QtWidgets.QGroupBox("控制")
        control_layout = QtWidgets.QHBoxLayout(control_box)
        self.pause_button = QtWidgets.QPushButton("暂停")
        self.reset_button = QtWidgets.QPushButton("复位")
        self.stop_button = QtWidgets.QPushButton("紧急停止")
        self.stop_button.setStyleSheet(
            "background-color: #8b1a1a; color: white; font-weight: bold;"
        )
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.reset_button)
        control_layout.addWidget(self.stop_button)
        root.addWidget(control_box)

        # 最近结果
        result_box = QtWidgets.QGroupBox("最近一次点击结果")
        result_layout = QtWidgets.QVBoxLayout(result_box)
        self.result_label = QtWidgets.QLabel("尚无点击")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        result_layout.addWidget(self.result_label)
        root.addWidget(result_box)

        # 日志
        log_box = QtWidgets.QGroupBox("最近操作日志")
        log_layout = QtWidgets.QVBoxLayout(log_box)
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(260)
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box)

    def _connect_signals(self) -> None:
        self.move_button.clicked.connect(self._on_move)
        self.click_button.clicked.connect(self._on_click)
        self.visible_button.clicked.connect(self._on_toggle_visible)
        self.pause_button.clicked.connect(self._on_pause_resume)
        self.reset_button.clicked.connect(self.controller.reset)
        self.stop_button.clicked.connect(
            lambda: self.controller.emergency_stop("控制面板按钮")
        )
        self.controller.log_emitted.connect(self._append_log)
        self.controller.state_changed.connect(self._sync_state)
        self.controller.click_finished.connect(self._on_click_finished)

    def _coord(self) -> DesktopCoordinate:
        return DesktopCoordinate(self.x_spin.value(), self.y_spin.value())

    def _on_move(self) -> None:
        self.controller.move_to(self._coord())

    def _on_click(self) -> None:
        self.controller.click_at(self._coord())

    def _on_toggle_visible(self) -> None:
        visible = not self.controller.overlay.isVisible()
        self.controller.set_overlay_visible(visible)
        self.visible_button.setText("显示圆点" if not visible else "隐藏圆点")

    def _on_pause_resume(self) -> None:
        if self.controller.state.value == "paused":
            self.controller.resume()
        else:
            self.controller.pause()
        self._sync_pause_button()

    def _sync_state(self, state: str) -> None:
        self.status_label.setText(settings.STATE_LABELS.get(state, state))
        self._sync_pause_button()

    def _sync_pause_button(self) -> None:
        self.pause_button.setText(
            "恢复" if self.controller.state.value == "paused" else "暂停"
        )

    def _on_click_finished(self, result) -> None:
        if result is None:
            self.result_label.setText("点击被拒绝")
            return
        lines = [
            f"目标：{result.target.describe()}",
            f"状态：{result.status.value}",
            f"消息入队：{'全部成功' if result.all_messages_queued else '未全部成功'}",
            f"按键释放不确定：{'是' if result.button_release_uncertain else '否'}",
            f"实际点击验证：{result.verification}",
        ]
        for err in result.errors:
            lines.append(f"错误：{err}")
        self.result_label.setText("\n".join(lines))

    def _append_log(self, message: str) -> None:
        self.log_view.append(message)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
