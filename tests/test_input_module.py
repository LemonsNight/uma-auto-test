"""阶段 3/4 验证：输入模块 + 状态机 + 全局热键 + 禁用 API 静态检查。

运行：
    python tests/test_input_module.py
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

import win32api
import win32con
import win32gui

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import (  # noqa: E402
    DesktopCoordinate,
    enable_per_monitor_dpi_awareness,
    make_lparam,
    unpack_lparam,
)

enable_per_monitor_dpi_awareness()

from PySide6 import QtCore, QtWidgets  # noqa: E402

from core.hotkey import GlobalHotkey  # noqa: E402
from core.input_backend import (  # noqa: E402
    MK_LBUTTON,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    PostMessageBackend,
)
from core.virtual_cursor import CursorState, VirtualCursorController  # noqa: E402
from core.window_resolver import CoordinateMapper, WindowResolver  # noqa: E402
from overlay.cursor_renderer import CursorRenderer  # noqa: E402
from overlay.overlay_window import OverlayWindow  # noqa: E402

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(REPORT_DIR / "phase3_input.log", mode="w", encoding="utf-8"),
    ],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


class FakeOverlay:
    """测试用 Overlay：只记录移动，不创建窗口。"""

    def __init__(self):
        self.positions: list[DesktopCoordinate] = []

    def move_to_desktop(self, coord: DesktopCoordinate) -> bool:
        self.positions.append(coord)
        return True

    def set_overlay_visible(self, visible: bool) -> None:
        pass


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)

    # 1. LPARAM 编解码
    ok = all(unpack_lparam(make_lparam(x, y)) == (x, y)
             for x, y in [(0, 0), (100, 200), (-32768, 32767), (3000, -40)])
    record("LPARAM 编解码（含负坐标）", ok, "4 组坐标往返一致")
    try:
        make_lparam(40000, 0)
        record("LPARAM 越界拒绝", False, "未抛出异常")
    except ValueError:
        record("LPARAM 越界拒绝", True, "超出 16 位有符号范围时抛出 ValueError")

    # 2. 静态检查：源码中不存在被禁止的输入 API
    forbidden = ("SetCursorPos", "SendInput", "mouse_event", "pyautogui")
    hits = []
    for path in REPO.rglob("*.py"):
        if "tests" in path.parts or "tools" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            # 文档字符串里出现"严禁..."不算调用，检查实际调用形式。
            if f"{token}(" in text:
                hits.append(f"{path.name}:{token}")
    record("禁用输入 API 静态检查", not hits, f"命中={hits}")

    # 3. 真实 Overlay + 解析器 + PostMessage 后端
    overlay = OverlayWindow(CursorRenderer())
    overlay.set_overlay_visible(True)
    target_widget = QtWidgets.QLabel("POSTMESSAGE_TEST_TARGET")
    target_widget.setWindowTitle("PostMessage Test Target")
    target_widget.setWindowFlags(
        QtCore.Qt.WindowType.WindowStaysOnTopHint
        | QtCore.Qt.WindowType.FramelessWindowHint
    )
    target_widget.setFixedSize(320, 200)
    target_widget.move(40, 900)  # 避开其它程序窗口
    target_widget.show()
    target_widget.raise_()
    QtWidgets.QApplication.processEvents()

    center_desktop = target_widget.mapToGlobal(target_widget.rect().center())
    coord = DesktopCoordinate(center_desktop.x(), center_desktop.y())
    resolver = WindowResolver(CoordinateMapper(), overlay_title=overlay.windowTitle())
    target = resolver.resolve(coord)
    record(
        "WindowFromPoint 解析到测试窗口",
        target.hwnd == int(target_widget.winId()) and not target.reject_reason,
        f"{target.describe()} reject={target.reject_reason}",
    )

    backend = PostMessageBackend()
    click = backend.click(coord, target)
    ids = [m.message_id for m in click.messages]
    wparams = [m.wparam for m in click.messages]
    ok = ids == [WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP] and wparams == [0, MK_LBUTTON, 0]
    record(
        "PostMessage 三条消息顺序与 wParam",
        ok,
        f"ids={[hex(i) for i in ids]} wparams={[hex(w) for w in wparams]}",
    )
    record(
        "PostMessage 全部入队成功",
        click.all_messages_queued,
        click.describe(),
    )
    record(
        "入队成功与实际验证严格区分",
        "未验证" in click.verification,
        click.verification,
    )

    # 4. 桌面窗口拒绝
    desktop_hwnd = int(win32gui.FindWindow("Progman", None))
    reason = resolver._check_reject("Progman", "Program Manager", desktop_hwnd)
    record("拒绝向系统桌面窗口发送点击", bool(reason), f"reason={reason}")

    # 5. 状态机
    fake_overlay = FakeOverlay()
    controller = VirtualCursorController(fake_overlay, resolver, backend)
    controller.start()
    record("启动后状态 running", controller.state is CursorState.RUNNING, controller.state.value)

    controller.pause()
    paused_result = controller.click_at(coord)
    record("暂停时拒绝点击", paused_result is None, f"state={controller.state.value}")

    controller.resume()
    resumed_result = controller.click_at(coord)
    record("恢复后允许点击", resumed_result is not None and resumed_result.all_messages_queued,
           f"state={controller.state.value}")

    controller.emergency_stop("测试")
    stopped_result = controller.click_at(coord)
    stopped_move = controller.move_to(coord)
    record(
        "紧急停止立即拒绝点击与移动",
        controller.state is CursorState.STOPPED and stopped_result is None and not stopped_move,
        f"state={controller.state.value} click={stopped_result} move={stopped_move}",
    )

    controller.reset()
    record("复位后恢复运行", controller.state is CursorState.RUNNING, controller.state.value)

    # 6. 全局热键链路（用 WM_HOTKEY 投递模拟触发，不合成真实键盘输入）
    hotkey = GlobalHotkey(target_widget.winId, settings.HOTKEY_MODIFIERS,
                          settings.HOTKEY_VK, settings.HOTKEY_LABEL)
    hotkey.triggered.connect(lambda: controller.emergency_stop("测试热键触发"))
    registered = hotkey.register()
    record("全局热键注册", registered, f"label={settings.HOTKEY_LABEL} registered={registered}")
    posted = hotkey.simulate_for_test()
    for _ in range(20):
        app.processEvents()
    record(
        "全局热键触发紧急停止",
        posted and controller.state is CursorState.STOPPED,
        f"模拟投递={posted} state={controller.state.value}",
    )
    hotkey.unregister()

    # 7. 报告
    lines = [
        "# 阶段 3/4：输入模块、状态机与热键测试报告",
        "",
        "| 验证项 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail.replace(chr(10), ' / ')} |")
    lines += [
        "",
        "## 关键语义",
        "",
        "- PostMessage 返回 True 仅代表消息入队，不代表目标程序处理了点击。",
        "- 本测试中的目标窗口是测试用 QLabel，不是业务程序。",
        "",
    ]
    (REPORT_DIR / "phase3_input_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n阶段 3/4 结果：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
