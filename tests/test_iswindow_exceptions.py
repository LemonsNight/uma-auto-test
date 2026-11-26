"""Phase 1.1 Final Review — IsWindow 异常安全补丁测试。

运行：
    python tests/test_iswindow_exceptions.py

关键点：Mock 精确控制"第 N 次 IsWindow / IsWindowEnabled 调用"抛异常。
resolve() 中 IsWindow 会被多处调用（初始命中、GetAncestor 验证、
_walk_chain、最终目标检查、mapper），若只让 Mock 无条件抛异常，
测试只会覆盖最早的前置检查，无法验证本轮修复的分支。

覆盖：
1. GetAncestor 正常，但验证其有效性的 IsWindow 抛异常。
2. 最终目标第二次 IsWindow（最终目标阶段）抛异常。
3. 最终目标 IsWindowEnabled 抛异常。
4. 每个拒绝场景 PostMessageBackend post_calls == 0。
5. 正常窗口与普通子窗口仍放行。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate  # noqa: E402
from core.input_backend import PostMessageBackend  # noqa: E402
from core.window_resolver import CoordinateMapper, WindowResolver  # noqa: E402

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_iswindow.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


class Node:
    def __init__(self, hwnd, cls, title="", parent=0, rect=(0, 0, 300, 300)):
        self.hwnd, self.cls, self.title = hwnd, cls, title
        self.parent, self.rect = parent, rect


class CountingApi:
    """可精确控制第 N 次 IsWindow / IsWindowEnabled 抛异常的模拟 API。"""

    def __init__(self, nodes, hit, *, is_window_fail_at=None, enabled_fail_at=None):
        self.nodes = nodes
        self.hit = hit
        self.is_window_fail_at = is_window_fail_at
        self.enabled_fail_at = enabled_fail_at
        self.is_window_calls = 0
        self.enabled_calls = 0
        self.post_calls: list[tuple] = []
        self.child = 0

    def _bump_is_window(self):
        self.is_window_calls += 1
        return self.is_window_calls

    def is_window(self, hwnd):
        nth = self._bump_is_window()
        if self.is_window_fail_at == nth:
            raise RuntimeError(f"模拟第 {nth} 次 IsWindow 异常")
        return hwnd in self.nodes

    def is_window_enabled(self, hwnd):
        self.enabled_calls += 1
        if self.enabled_fail_at == self.enabled_calls:
            raise RuntimeError(f"模拟第 {self.enabled_calls} 次 IsWindowEnabled 异常")
        return True

    def window_from_point(self, x, y):
        return self.hit

    def get_ancestor(self, hwnd, flag):
        return self.hit

    def get_class_name(self, hwnd):
        return self.nodes.get(hwnd).cls if hwnd in self.nodes else ""

    def get_window_text(self, hwnd):
        return self.nodes.get(hwnd).title if hwnd in self.nodes else ""

    def get_parent(self, hwnd):
        node = self.nodes.get(hwnd)
        return node.parent if node else 0

    def get_window_rect(self, hwnd):
        return self.nodes.get(hwnd).rect if hwnd in self.nodes else (0, 0, 0, 0)

    def get_client_rect(self, hwnd):
        return (0, 0, 300, 300)

    def screen_to_client(self, hwnd, x, y):
        return x, y

    def real_child_window_from_point(self, hwnd, client_x, client_y):
        return self.child

    def post_message(self, *args):
        self.post_calls.append(args)
        return True, 0


def make_resolver(api):
    return WindowResolver(
        CoordinateMapper(api=api),
        api=api,
        overlay_title="VirtualMouse Overlay",
    )


def assert_no_post(name: str, api: CountingApi, result) -> None:
    backend = PostMessageBackend(post_fn=api.post_message, is_window_fn=lambda h: True)
    click = backend.click(DesktopCoordinate(50, 50), result)
    record(
        f"{name} -> 后端 PostMessage 调用数为 0",
        len(api.post_calls) == 0 and not click.all_messages_queued,
        f"post_calls={len(api.post_calls)} status={click.status.value}",
    )


def main() -> int:
    coord = DesktopCoordinate(50, 50)

    # 先跑正常路径，统计 IsWindow 调用序号，便于精确定位第 N 次。
    root = Node(1, "MyApp", "应用")
    probe_api = CountingApi({1: root}, 1)
    probe = make_resolver(probe_api).resolve(coord)
    call_order = probe_api.is_window_calls
    record("正常窗口放行并统计 IsWindow 调用",
           not probe.reject_reason and call_order >= 3,
           f"reject={probe.reject_reason} total_iswindow_calls={call_order}")

    # 1) GetAncestor 正常返回，但验证其有效性的 IsWindow（第 2 次）抛异常
    api_ancestor = CountingApi({1: root}, 1, is_window_fail_at=2)
    r1 = make_resolver(api_ancestor).resolve(coord)
    record(
        "IsWindow(ancestor) 抛异常 -> 明确拒绝",
        bool(r1.reject_reason) and not r1.chain_reliable
        and r1.root_hwnd == 0 and "IsWindow(ancestor)" in r1.reject_reason,
        f"reason={r1.reject_reason} reliable={r1.chain_reliable} "
        f"root=0x{r1.root_hwnd:X} nth={api_ancestor.is_window_calls}",
    )
    assert_no_post("IsWindow(ancestor) 异常", api_ancestor, r1)

    # 2) 最终目标阶段的 IsWindow 抛异常。
    # 正常流程中第 N 次（N=total-1）通常对应 mapper 前的最终目标检查；
    # 用一个先探测再精确设置的模式：从第 3 次开始逐个尝试，
    # 直到拒绝原因明确来自"最终目标 IsWindow"。
    final_target_case = None
    for nth in range(3, call_order + 2):
        api = CountingApi({1: root}, 1, is_window_fail_at=nth)
        try:
            r = make_resolver(api).resolve(coord)
        except Exception as exc:
            final_target_case = ("LEAK", nth, f"异常泄漏: {exc}")
            break
        if r.reject_reason and "最终目标 IsWindow 查询异常" in r.reject_reason:
            final_target_case = ("OK", nth, r)
            break
    if final_target_case is None:
        record("最终目标 IsWindow 异常 -> 明确拒绝", False, "未找到对应调用序号")
    elif final_target_case[0] == "LEAK":
        record("最终目标 IsWindow 异常 -> 不泄漏异常", False, final_target_case[2])
    else:
        _, nth, r = final_target_case
        record(
            "最终目标 IsWindow 异常 -> 明确拒绝",
            bool(r.reject_reason) and not r.is_safe_target,
            f"reason={r.reject_reason} nth={nth}",
        )
        api = CountingApi({1: root}, 1, is_window_fail_at=nth)
        r = make_resolver(api).resolve(coord)
        assert_no_post("最终目标 IsWindow 异常", api, r)

    # 3) 最终目标 IsWindowEnabled 抛异常
    api_enabled = CountingApi({1: root}, 1, enabled_fail_at=1)
    try:
        r3 = make_resolver(api_enabled).resolve(coord)
        leaked = False
    except Exception as exc:
        r3 = None
        leaked = True
        leak_detail = str(exc)
    record(
        "最终目标 IsWindowEnabled 异常不泄漏",
        not leaked,
        "未泄漏" if not leaked else f"异常泄漏: {leak_detail}",
    )
    if not leaked:
        record(
            "最终目标 IsWindowEnabled 异常 -> 明确拒绝",
            bool(r3.reject_reason) and "IsWindowEnabled 查询异常" in r3.reject_reason,
            f"reason={r3.reject_reason} enabled_calls={api_enabled.enabled_calls}",
        )
        assert_no_post("最终目标 IsWindowEnabled 异常", api_enabled, r3)

    # 4) 普通应用正常子窗口仍放行
    root_node = Node(10, "AppRoot", "应用", rect=(0, 0, 400, 400))
    child_node = Node(11, "ChildClass", "子窗口", parent=10,
                      rect=(40, 40, 200, 200))
    child_api = CountingApi({10: root_node, 11: child_node}, 10)
    child_api.child = 11
    r_child = make_resolver(child_api).resolve(coord)
    record(
        "普通应用正常子窗口仍然放行",
        r_child.hwnd == 11 and not r_child.reject_reason,
        f"target=0x{r_child.hwnd:X} reason={r_child.reject_reason}",
    )

    lines = [
        "# Phase 1.1 Final Review — IsWindow 异常安全补丁测试报告",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += [
        "",
        "Mock 使用调用计数精确控制第 N 次 IsWindow / IsWindowEnabled 抛异常，",
        "避免只覆盖 _walk_chain 的前置检查。所有拒绝场景均通过",
        "PostMessageBackend 注入 post_fn 验证调用数为 0。",
        "",
    ]
    (REPORT_DIR / "phase11_iswindow_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\nIsWindow 异常安全测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
