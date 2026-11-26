"""Phase 1.1 Review Fix：父窗口链类名/句柄读取失败安全测试。

运行：
    python tests/test_window_chain_errors.py

覆盖：
- 命中窗口 GetClassName 抛异常 -> 拒绝
- 中间父窗口 GetClassName 抛异常 -> 拒绝
- GetWindowText 抛异常但类名正常 -> 仅诊断，不放行拒绝
- 正常桌面父窗口链仍然拒绝
- 普通应用 SysListView32 仍然允许
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate  # noqa: E402
from core.window_resolver import CoordinateMapper, WindowApi, WindowResolver  # noqa: E402

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_review_chain.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


class Node:
    def __init__(self, hwnd, cls, title="", parent=0, rect=(0, 0, 100, 100)):
        self.hwnd, self.cls, self.title = hwnd, cls, title
        self.parent, self.rect = parent, rect


class StrictMockApi(WindowApi):
    """可模拟查询异常的模拟窗口树。"""

    def __init__(self, nodes, hit, *, class_error=(), title_error=(),
                 parent_error=(), is_window_error=()):
        self.nodes = nodes
        self.hit = hit
        self.class_error = set(class_error)
        self.title_error = set(title_error)
        self.parent_error = set(parent_error)
        self.is_window_error = set(is_window_error)

    def window_from_point(self, x, y):
        return self.hit

    def is_window(self, hwnd):
        if hwnd in self.is_window_error:
            raise RuntimeError("模拟 IsWindow 异常")
        return hwnd in self.nodes

    def get_class_name(self, hwnd):
        if hwnd in self.class_error:
            raise RuntimeError("模拟 GetClassName 异常")
        node = self.nodes.get(hwnd)
        return node.cls if node else ""

    def get_window_text(self, hwnd):
        if hwnd in self.title_error:
            raise RuntimeError("模拟 GetWindowText 异常")
        node = self.nodes.get(hwnd)
        return node.title if node else ""

    def get_parent(self, hwnd):
        if hwnd in self.parent_error:
            raise RuntimeError("模拟 GetParent 异常")
        node = self.nodes.get(hwnd)
        return node.parent if node else 0

    def get_ancestor(self, hwnd, flag):
        return self.hit

    def real_child_window_from_point(self, hwnd, client_x, client_y):
        return 0

    def get_window_rect(self, hwnd):
        return self.nodes.get(hwnd).rect if hwnd in self.nodes else (0, 0, 0, 0)

    def screen_to_client(self, hwnd, x, y):
        return (x, y)

    def get_client_rect(self, hwnd):
        return (0, 0, 100, 100)

    def is_window_enabled(self, hwnd):
        return True


def make_resolver(nodes, hit, **kwargs):
    api = StrictMockApi(nodes, hit, **kwargs)
    return WindowResolver(CoordinateMapper(api=api), api=api), api


def main() -> int:
    coord = DesktopCoordinate(50, 50)

    # 1. 命中窗口 GetClassName 抛异常
    nodes = {1: Node(1, "MyApp", "应用")}
    resolver, _ = make_resolver(nodes, 1, class_error={1})
    r = resolver.resolve(coord)
    record("命中窗口 GetClassName 异常 -> 拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason} reliable={r.chain_reliable}")

    # 2. 中间父窗口 GetClassName 抛异常
    nodes = {
        10: Node(10, "Child", "子窗口", parent=11),
        11: Node(11, "Parent", "父窗口"),
    }
    resolver, _ = make_resolver(nodes, 10, class_error={11})
    r = resolver.resolve(coord)
    record("中间父窗口 GetClassName 异常 -> 拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason} reliable={r.chain_reliable}")

    # 3. GetWindowText 抛异常但类名正常 -> 允许（仅诊断）
    nodes = {20: Node(20, "MyApp", "应用")}
    resolver, _ = make_resolver(nodes, 20, title_error={20})
    r = resolver.resolve(coord)
    title_flags = [n.title_read_failed for n in r.chain]
    record("GetWindowText 异常但类名正常 -> 不因标题拒绝",
           not r.reject_reason and any(title_flags),
           f"reason={r.reject_reason} title_flags={title_flags}")

    # 4. 正常桌面父窗口链仍然拒绝
    nodes = {
        30: Node(30, "Progman", "Program Manager"),
        31: Node(31, "SHELLDLL_DefView", parent=30),
        32: Node(32, "SysListView32", "FolderView", parent=31),
    }
    resolver, _ = make_resolver(nodes, 32)
    r = resolver.resolve(coord)
    record("桌面父窗口链仍然拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason} chain={[n.class_name for n in r.chain]}")

    # 5. 普通应用 SysListView32 仍然允许
    nodes = {
        40: Node(40, "MyApp", "资源管理器"),
        41: Node(41, "SysListView32", "文件列表", parent=40),
    }
    resolver, _ = make_resolver(nodes, 41)
    r = resolver.resolve(coord)
    record("普通应用 SysListView32 仍然允许", not r.reject_reason,
           f"reason={r.reject_reason} chain={[n.class_name for n in r.chain]}")

    # 6. GetParent 异常 -> 安全失败
    nodes = {50: Node(50, "MyApp", "应用")}
    resolver, _ = make_resolver(nodes, 50, parent_error={50})
    r = resolver.resolve(coord)
    record("GetParent 异常 -> 安全失败", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 7. IsWindow 异常 -> 安全失败
    nodes = {60: Node(60, "MyApp", "应用")}
    resolver, _ = make_resolver(nodes, 60, is_window_error={60})
    r = resolver.resolve(coord)
    record("IsWindow 异常 -> 安全失败", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    lines = [
        "# Phase 1.1 Review Fix：父窗口链异常安全测试报告",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += ["", "全部使用模拟窗口树，未点击任何真实窗口。", ""]
    (REPORT_DIR / "phase11_review_chain_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n窗口链异常测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
