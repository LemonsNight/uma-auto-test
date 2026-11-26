"""Phase 1.1：点击消息状态管理测试（Mock PostMessage，不产生真实点击）。

运行：
    python tests/test_click_state.py

覆盖：
- 三条消息全部成功
- MOUSEMOVE / DOWN / UP 各自失败
- DOWN 成功后 HWND 被销毁（不再补发给其它窗口）
- 失败时结果对象不能报告完整成功
- 释放补救结果与异常状态保留
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate  # noqa: E402
from core.input_backend import (  # noqa: E402
    MK_LBUTTON,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    ClickStatus,
    PostMessageBackend,
)
from core.window_resolver import ResolvedTarget  # noqa: E402

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_click_state.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


def make_target(hwnd: int = 0x1234, safe: bool = True) -> ResolvedTarget:
    return ResolvedTarget(
        hwnd=hwnd,
        title="测试目标",
        class_name="TestWindow",
        client_x=100,
        client_y=200,
        root_hwnd=hwnd,
        root_title="测试目标",
        reject_reason=None if safe else "模拟拒绝",
    )


class FakePost:
    """记录每次 PostMessage 调用；按消息 ID 配置失败。"""

    def __init__(self, fail_on: set[int] | None = None,
                 fail_first_only: set[int] | None = None,
                 destroy_after: int | None = None) -> None:
        self.fail_on = fail_on or set()
        self.fail_first_only = set(fail_first_only or set())
        self.destroy_after = destroy_after
        self.calls: list[tuple[int, int, int, int]] = []

    def __call__(self, hwnd, msg, wparam, lparam):
        self.calls.append((hwnd, msg, wparam, lparam))
        if msg in self.fail_on:
            return False, 5
        if msg in self.fail_first_only:
            self.fail_first_only.discard(msg)
            return False, 5
        if self.destroy_after is not None and msg == self.destroy_after:
            self.alive = False
        return True, 0


class FakeWindow:
    def __init__(self, initially_alive: bool = True) -> None:
        self.alive = initially_alive

    def __call__(self, hwnd):
        return self.alive


class FailReleasePost:
    """所有 LBUTTONUP（含补救）都失败，MOUSEMOVE/DOWN 成功。"""

    def __init__(self):
        self.calls = []

    def __call__(self, hwnd, msg, wparam, lparam):
        self.calls.append((hwnd, msg, wparam, lparam))
        if msg == WM_LBUTTONUP:
            return False, 5
        return True, 0


def main() -> int:
    coord = DesktopCoordinate(500, 400)

    # 1. 三条消息全部成功
    post = FakePost()
    alive = FakeWindow()
    r = PostMessageBackend(post_fn=post, is_window_fn=alive).click(coord, make_target())
    ids = [c[1] for c in post.calls]
    record(
        "三条消息全部成功 -> COMPLETE_QUEUED",
        r.status is ClickStatus.COMPLETE_QUEUED and r.all_messages_queued and r.is_complete,
        f"status={r.status.value} ids={[hex(i) for i in ids]}",
    )
    record(
        "完整入队仍标记为实际点击未验证",
        "未验证" in r.verification,
        r.verification,
    )

    # 2. MOUSEMOVE 失败：不发 DOWN / UP
    post = FakePost(fail_on={WM_MOUSEMOVE})
    alive = FakeWindow()
    r = PostMessageBackend(post_fn=post, is_window_fn=alive).click(coord, make_target())
    ids = [c[1] for c in post.calls]
    record(
        "MOUSEMOVE 失败 -> 停止且不发 DOWN/UP",
        r.status is ClickStatus.MOUSEMOVE_FAILED and ids == [WM_MOUSEMOVE]
        and not r.all_messages_queued,
        f"status={r.status.value} ids={[hex(i) for i in ids]}",
    )

    # 3. DOWN 失败：不发正常 UP
    post = FakePost(fail_on={WM_LBUTTONDOWN})
    alive = FakeWindow()
    r = PostMessageBackend(post_fn=post, is_window_fn=alive).click(coord, make_target())
    ids = [c[1] for c in post.calls]
    record(
        "DOWN 失败 -> 不发正常 UP",
        r.status is ClickStatus.DOWN_FAILED and ids == [WM_MOUSEMOVE, WM_LBUTTONDOWN]
        and not r.all_messages_queued,
        f"status={r.status.value} ids={[hex(i) for i in ids]}",
    )

    # 4. UP 失败：尝试对原 HWND 补发释放，记录补救结果，不报告完整成功
    post = FakePost(fail_first_only={WM_LBUTTONUP})
    alive = FakeWindow()
    r = PostMessageBackend(post_fn=post, is_window_fn=alive).click(coord, make_target())
    ids = [c[1] for c in post.calls]
    record(
        "UP 失败 -> UP_FAILED 且补发释放到原 HWND",
        r.status is ClickStatus.UP_FAILED and ids.count(WM_LBUTTONUP) == 2
        and all(c[0] == 0x1234 for c in post.calls) and not r.all_messages_queued,
        f"status={r.status.value} ids={[hex(i) for i in ids]}",
    )
    record(
        "UP 失败 -> 保留未释放状态与补救结果",
        r.button_release_uncertain and r.release_recovery is not None
        and r.release_recovery.posted,
        f"uncertain={r.button_release_uncertain} recovery={r.release_recovery}",
    )

    # 5. DOWN 成功后 HWND 被销毁：不补发给其它窗口，明确无法保证释放
    post = FakePost(destroy_after=WM_LBUTTONDOWN)
    alive = FakeWindow()
    # 让 is_window 跟随 post 的 alive 状态
    def is_alive(hwnd):
        return getattr(post, "alive", True)

    r = PostMessageBackend(post_fn=post, is_window_fn=is_alive).click(coord, make_target())
    ids = [c[1] for c in post.calls]
    record(
        "DOWN 后 HWND 销毁 -> 不再发 UP / 不切换窗口",
        r.status is ClickStatus.UP_FAILED and ids == [WM_MOUSEMOVE, WM_LBUTTONDOWN]
        and r.button_release_uncertain and not r.all_messages_queued,
        f"status={r.status.value} ids={[hex(i) for i in ids]} checks="
        f"{[c.describe() for c in r.hwnd_checks]}",
    )
    record(
        "HWND 销毁 -> 明确报告无法保证释放且无补救",
        r.release_recovery is None
        and any("无法" in e or "不能保证" in e for e in r.errors),
        f"errors={r.errors}",
    )

    # 6. 发送前 HWND 已失效
    post = FakePost()
    r = PostMessageBackend(post_fn=post, is_window_fn=FakeWindow(False)).click(
        coord, make_target()
    )
    record(
        "发送前 HWND 失效 -> TARGET_INVALID 且零消息",
        r.status is ClickStatus.TARGET_INVALID and len(post.calls) == 0,
        f"status={r.status.value} calls={len(post.calls)}",
    )

    # 7. 目标被安全策略拒绝
    post = FakePost()
    r = PostMessageBackend(post_fn=post, is_window_fn=FakeWindow()).click(
        coord, make_target(safe=False)
    )
    record(
        "拒绝目标 -> REJECTED_TARGET 且零消息",
        r.status is ClickStatus.REJECTED_TARGET and len(post.calls) == 0,
        f"status={r.status.value} calls={len(post.calls)}",
    )

    # 8. LPARAM 越界 -> 不发送
    post = FakePost()
    bad = make_target()
    bad.client_x = 40000
    r = PostMessageBackend(post_fn=post, is_window_fn=FakeWindow()).click(coord, bad)
    record(
        "LPARAM 越界 -> LPARAM_OUT_OF_RANGE 且零消息",
        r.status is ClickStatus.LPARAM_OUT_OF_RANGE and len(post.calls) == 0,
        f"status={r.status.value} calls={len(post.calls)}",
    )

    # 9. 补救释放也失败 -> 保留异常状态
    post = FailReleasePost()
    r = PostMessageBackend(post_fn=post, is_window_fn=FakeWindow()).click(coord, make_target())
    record(
        "补救释放失败 -> 仍为 UP_FAILED 且保留原因",
        r.status is ClickStatus.UP_FAILED and r.button_release_uncertain
        and r.release_recovery is not None and not r.release_recovery.posted
        and any("仍失败" in e or "无法保证" in e for e in r.errors),
        f"status={r.status.value} recovery={r.release_recovery.describe()} errors={r.errors}",
    )

    lines = [
        "# Phase 1.1：点击消息状态管理测试报告（Mock PostMessage）",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += [
        "",
        "所有失败分支均通过注入的 post_fn / is_window_fn 模拟，未产生真实点击。",
        "",
    ]
    (REPORT_DIR / "phase11_click_state_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n点击状态测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
