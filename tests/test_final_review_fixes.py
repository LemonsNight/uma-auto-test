"""Phase 1.1 Final Review：最后三项安全性修复测试。

运行：
    python tests/test_final_review_fixes.py

覆盖：
- GetAncestor 异常 -> 明确拒绝、chain_reliable=False、不发送输入
- 候选子窗口不安全 / 失效 / 父链异常 -> 拒绝且不回退根窗口
- 普通应用正常子窗口继续放行
- DPI 查询优先进程级、线程回退语义、完全失败 UNKNOWN
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import (  # noqa: E402
    DpiAwareness,
    _apply_dpi_awareness_detailed,
    reset_dpi_state_for_test,
)
from core.coordinate import (  # noqa: E402
    current_dpi_source,
    enable_per_monitor_dpi_awareness,
)
from core.coordinate import query_dpi_awareness_detailed  # noqa: E402

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_final_review.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


class Node:
    def __init__(self, hwnd, cls, title="", parent=0, rect=(0, 0, 100, 100),
                 origin=(0, 0)):
        self.hwnd, self.cls, self.title = hwnd, cls, title
        self.parent, self.rect, self.origin = parent, rect, origin


class FinalMockApi:
    """可模拟 GetAncestor / 候选子窗口异常的 API。"""

    def __init__(self, nodes, hit, *, ancestor_error=False, ancestor_invalid=False,
                 child_class_error=(), child_parent_error=(), dead_child=False):
        self.nodes = nodes
        self.hit = hit
        self.ancestor_error = ancestor_error
        self.ancestor_invalid = ancestor_invalid
        self.child_class_error = set(child_class_error)
        self.child_parent_error = set(child_parent_error)
        self.dead_child = dead_child
        self.child = 0
        self.post_calls: list[tuple] = []
        self.real_child_calls = 0

    def window_from_point(self, x, y):
        return self.hit

    def is_window(self, hwnd):
        if self.dead_child and hwnd == self.child:
            return False
        return hwnd in self.nodes

    def is_window_enabled(self, hwnd):
        return True

    def get_ancestor(self, hwnd, flag):
        if self.ancestor_error:
            raise RuntimeError("模拟 GetAncestor 异常")
        if self.ancestor_invalid:
            return 0
        return self.hit

    def get_class_name(self, hwnd):
        if hwnd in self.child_class_error:
            raise RuntimeError("模拟候选子窗口 GetClassName 异常")
        return self.nodes.get(hwnd).cls if hwnd in self.nodes else ""

    def get_window_text(self, hwnd):
        return self.nodes.get(hwnd).title if hwnd in self.nodes else ""

    def get_parent(self, hwnd):
        if hwnd in self.child_parent_error:
            raise RuntimeError("模拟候选子窗口父链异常")
        node = self.nodes.get(hwnd)
        return node.parent if node else 0

    def get_window_rect(self, hwnd):
        return self.nodes.get(hwnd).rect if hwnd in self.nodes else (0, 0, 0, 0)

    def get_client_rect(self, hwnd):
        return (0, 0, 100, 100)

    def screen_to_client(self, hwnd, x, y):
        node = self.nodes.get(hwnd)
        if not node:
            raise RuntimeError("未知 HWND")
        return x - node.origin[0], y - node.origin[1]

    def real_child_window_from_point(self, hwnd, client_x, client_y):
        self.real_child_calls += 1
        return self.child

    def post_message(self, *args):
        """Backend 注入用；任何调用都记录，测试断言为 0。"""
        self.post_calls.append(args)
        return True, 0


def make_resolver(api):
    from core.window_resolver import CoordinateMapper, WindowResolver
    return WindowResolver(CoordinateMapper(api=api), api=api)


def main() -> int:
    from core.coordinate import DesktopCoordinate
    coord = DesktopCoordinate(50, 50)

    # ---------- 任务 1：GetAncestor 异常 ----------
    root_node = Node(1, "MyApp", "应用", rect=(0, 0, 300, 300))
    api = FinalMockApi({1: root_node}, 1, ancestor_error=True)
    resolver = make_resolver(api)
    r = resolver.resolve(coord)
    record("GetAncestor 异常 -> 拒绝且 chain_reliable=False",
           bool(r.reject_reason) and not r.chain_reliable and "GetAncestor" in r.reject_reason,
           f"reason={r.reject_reason} reliable={r.chain_reliable}")
    record("GetAncestor 异常 -> 未把 hit_hwnd 当成 root",
           r.root_hwnd == 0 and r.hwnd == 1,
           f"root=0x{r.root_hwnd:X} hit=0x{r.hwnd:X}")
    record("GetAncestor 异常 -> resolve 不抛出未处理异常",
           True, "调用正常返回 ResolvedTarget")

    # 后端不发送：构造一个记录 post 调用的 backend
    from core.input_backend import PostMessageBackend
    backend = PostMessageBackend(post_fn=api.post_message, is_window_fn=lambda h: True)
    click = backend.click(coord, r)
    record("GetAncestor 异常 -> 后端不发送 PostMessage",
           len(api.post_calls) == 0 and not click.all_messages_queued,
           f"post_calls={len(api.post_calls)} status={click.status.value}")

    api2 = FinalMockApi({1: root_node}, 1, ancestor_invalid=True)
    r2 = make_resolver(api2).resolve(coord)
    record("GetAncestor 返回无效 HWND -> 拒绝",
           bool(r2.reject_reason) and not r2.chain_reliable,
           f"reason={r2.reject_reason}")

    # ---------- 任务 2：候选子窗口 ----------
    # 根窗口在 (0,0)，桌面坐标 (50,50) -> 客户区 (50,50)，子窗口 rect 包含该点。
    child_rect = (40, 40, 200, 200)
    app_root = Node(10, "MyAppWindow", "应用", rect=(0, 0, 400, 400))
    normal_child = Node(11, "ChildClass", "子窗口", parent=10, rect=child_rect)

    # (a) 普通应用正常子窗口放行
    api_ok = FinalMockApi({10: app_root, 11: normal_child}, 10)
    api_ok.child = 11
    r_ok = make_resolver(api_ok).resolve(coord)
    record("普通应用正常子窗口继续放行",
           r_ok.hwnd == 11 and not r_ok.reject_reason,
           f"target=0x{r_ok.hwnd:X} reject={r_ok.reject_reason}")

    # (b) 候选子窗口属于桌面结构
    # 命中根窗口是普通应用，候选子窗口的父链才包含桌面结构。
    desk_root = Node(20, "AppRoot", "普通应用根窗口", rect=(0, 0, 400, 400))
    desk_view = Node(21, "SHELLDLL_DefView", parent=20, rect=(0, 0, 400, 400))
    desk_child = Node(22, "SysListView32", "FolderView", parent=21, rect=child_rect)
    api_desk = FinalMockApi({20: desk_root, 21: desk_view, 22: desk_child}, 20)
    api_desk.child = 22
    r_desk = make_resolver(api_desk).resolve(coord)
    record("候选子窗口属于桌面结构 -> 拒绝不回退根",
           bool(r_desk.reject_reason) and r_desk.hwnd == 22,
           f"target=0x{r_desk.hwnd:X} reason={r_desk.reject_reason}")
    backend = PostMessageBackend(post_fn=api_desk.post_message, is_window_fn=lambda h: True)
    click = backend.click(coord, r_desk)
    record("桌面候选子窗口 -> 后端不发送",
           len(api_desk.post_calls) == 0,
           f"post_calls={len(api_desk.post_calls)}")

    # (c) 候选子窗口父链查询异常
    api_parent = FinalMockApi(
        {10: app_root, 11: normal_child}, 10, child_parent_error={11}
    )
    api_parent.child = 11
    r_parent = make_resolver(api_parent).resolve(coord)
    record("候选子窗口父链异常 -> 拒绝",
           bool(r_parent.reject_reason) and r_parent.hwnd == 11,
           f"reason={r_parent.reject_reason}")
    backend = PostMessageBackend(post_fn=api_parent.post_message, is_window_fn=lambda h: True)
    backend.click(coord, r_parent)
    record("候选子窗口父链异常 -> 后端不发送",
           len(api_parent.post_calls) == 0,
           f"post_calls={len(api_parent.post_calls)}")

    # (d) 候选子窗口 HWND 失效
    api_dead = FinalMockApi({10: app_root, 11: normal_child}, 10, dead_child=True)
    api_dead.child = 11
    r_dead = make_resolver(api_dead).resolve(coord)
    record("候选子窗口 HWND 失效 -> 拒绝",
           bool(r_dead.reject_reason) and r_dead.hwnd == 11,
           f"reason={r_dead.reject_reason}")
    backend = PostMessageBackend(post_fn=api_dead.post_message, is_window_fn=lambda h: True)
    backend.click(coord, r_dead)
    record("候选子窗口失效 -> 后端不发送",
           len(api_dead.post_calls) == 0,
           f"post_calls={len(api_dead.post_calls)}")

    # (e) 候选子窗口 GetClassName 异常
    api_cls = FinalMockApi({10: app_root, 11: normal_child}, 10,
                           child_class_error={11})
    api_cls.child = 11
    r_cls = make_resolver(api_cls).resolve(coord)
    record("候选子窗口 GetClassName 异常 -> 拒绝",
           bool(r_cls.reject_reason),
           f"reason={r_cls.reject_reason}")

    # ---------- 任务 3：DPI 查询顺序与语义 ----------
    mode, source = _apply_dpi_awareness_detailed(
        lambda: True, lambda: True,
        lambda: (DpiAwareness.PER_MONITOR_AWARE, "process"),
    )
    record("进程级查询成功 -> source=process",
           mode == DpiAwareness.PER_MONITOR_AWARE and source == "process",
           f"mode={mode} source={source}")

    mode, source = _apply_dpi_awareness_detailed(
        lambda: True, lambda: True,
        lambda: (DpiAwareness.SYSTEM_AWARE, "thread_fallback"),
    )
    record("线程回退 -> source=thread_fallback",
           mode == DpiAwareness.SYSTEM_AWARE and source == "thread_fallback",
           f"mode={mode} source={source}")

    mode, source = _apply_dpi_awareness_detailed(
        lambda: True, lambda: True,
        lambda: (None, "unknown"),
    )
    record("进程与线程均失败 -> UNKNOWN",
           mode == DpiAwareness.UNKNOWN and source == "unknown",
           f"mode={mode} source={source}")

    # 真实查询优先级：直接检查 detailed 函数来源合法
    reset_dpi_state_for_test()
    note = enable_per_monitor_dpi_awareness()
    src = current_dpi_source()
    record("真实环境来源标记与诊断一致",
           (src == "process" and "进程级查询确认" in note)
           or (src == "thread_fallback" and "仅线程级回退结果" in note)
           or (src == "unknown" and "UNKNOWN" in note),
           f"src={src} note={note}")
    m, s = query_dpi_awareness_detailed()
    record("query_dpi_awareness_detailed 返回合法来源",
           s in ("process", "thread_fallback", "unknown"),
           f"mode={m} source={s}")

    lines = [
        "# Phase 1.1 Final Review：最后安全性修复测试报告",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += ["", "所有失败分支均使用 Mock，没有点击桌面图标。", ""]
    (REPORT_DIR / "phase11_final_review_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\nFinal Review 测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
