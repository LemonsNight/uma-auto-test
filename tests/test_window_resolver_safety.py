"""Phase 1.1：窗口解析安全测试（模拟窗口树，不点击桌面图标）。

运行：
    python tests/test_window_resolver_safety.py

覆盖：
- Progman / WorkerW / SHELLDLL_DefView 命中拒绝
- 桌面 SysListView32 子窗口拒绝
- 普通应用 SysListView32 不因类名被拒绝
- 父窗口链异常 / 成环 / 超深时安全失败
- 坐标转换失败不再继续发送
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate  # noqa: E402
from core.window_resolver import (  # noqa: E402
    CoordinateMapper,
    WindowApi,
    WindowResolver,
    _MAX_CHAIN_DEPTH,
)

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_resolver.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


class Node:
    def __init__(self, hwnd, cls, title="", parent=0, rect=(0, 0, 100, 100),
                 client=(0, 0, 100, 100)):
        self.hwnd = hwnd
        self.cls = cls
        self.title = title
        self.parent = parent
        self.rect = rect
        self.client = client


class MockWindowApi(WindowApi):
    """模拟窗口树；不调用任何真实 Win32 查询。"""

    def __init__(self, nodes: dict[int, Node], hit_hwnd: int, *,
                 raise_on_parent: set[int] | None = None) -> None:
        self.nodes = nodes
        self.hit_hwnd = hit_hwnd
        self.raise_on_parent = raise_on_parent or set()

    def window_from_point(self, x, y):
        return self.hit_hwnd

    def real_child_window_from_point(self, hwnd, x, y):
        return 0

    def get_parent(self, hwnd):
        if hwnd in self.raise_on_parent:
            raise RuntimeError("模拟父窗口查询异常")
        node = self.nodes.get(hwnd)
        return node.parent if node else 0

    def get_ancestor(self, hwnd, flag):
        cur = hwnd
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            node = self.nodes.get(cur)
            if not node or not node.parent:
                return cur
            cur = node.parent
        return hwnd

    def get_class_name(self, hwnd):
        return self.nodes.get(hwnd).cls if hwnd in self.nodes else ""

    def get_window_text(self, hwnd):
        return self.nodes.get(hwnd).title if hwnd in self.nodes else ""

    def is_window(self, hwnd):
        return hwnd in self.nodes

    def is_window_enabled(self, hwnd):
        return True

    def get_window_rect(self, hwnd):
        return self.nodes.get(hwnd).rect if hwnd in self.nodes else (0, 0, 0, 0)

    def screen_to_client(self, hwnd, x, y):
        return (x, y)

    def get_client_rect(self, hwnd):
        return self.nodes.get(hwnd).client if hwnd in self.nodes else (0, 0, 0, 0)


def resolver_for(nodes, hit, **kwargs):
    api = MockWindowApi(nodes, hit, **kwargs)
    return WindowResolver(CoordinateMapper(api=api), api=api), api


def main() -> int:
    coord = DesktopCoordinate(100, 100)

    # 1. Progman 直接命中
    nodes = {1: Node(1, "Progman", "Program Manager")}
    resolver, _ = resolver_for(nodes, 1)
    r = resolver.resolve(coord)
    record("命中 Progman 时拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 2. WorkerW 直接命中
    nodes = {2: Node(2, "WorkerW")}
    resolver, _ = resolver_for(nodes, 2)
    r = resolver.resolve(coord)
    record("命中 WorkerW 时拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 3. SHELLDLL_DefView 直接命中
    nodes = {3: Node(3, "SHELLDLL_DefView")}
    resolver, _ = resolver_for(nodes, 3)
    r = resolver.resolve(coord)
    record("命中 SHELLDLL_DefView 时拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 4. 桌面图标列表 SysListView32（父链含 SHELLDLL_DefView + Progman）
    nodes = {
        1: Node(1, "Progman", "Program Manager"),
        2: Node(2, "SHELLDLL_DefView", parent=1),
        3: Node(3, "SysListView32", "FolderView", parent=2),
    }
    resolver, _ = resolver_for(nodes, 3)
    r = resolver.resolve(coord)
    record("桌面 SysListView32 子窗口拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason} chain={[n.class_name for n in r.chain]}")

    # 5. WorkerW 分支的桌面 SysListView32
    nodes = {
        1: Node(1, "Progman", "Program Manager"),
        2: Node(2, "WorkerW", parent=1),
        3: Node(3, "SHELLDLL_DefView", parent=2),
        4: Node(4, "SysListView32", "FolderView", parent=3),
    }
    resolver, _ = resolver_for(nodes, 4)
    r = resolver.resolve(coord)
    record("WorkerW 下的桌面图标列表拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 6. 普通应用 SysListView32 不应因类名被拒绝
    nodes = {
        10: Node(10, "MyAppMainWindow", "我的应用"),
        11: Node(11, "SysListView32", "文件列表", parent=10),
    }
    resolver, _ = resolver_for(nodes, 11)
    r = resolver.resolve(coord)
    record("普通应用 SysListView32 不拒绝", not r.reject_reason,
           f"class={r.class_name} reason={r.reject_reason}")

    # 7. 父窗口链查询异常 -> 安全失败
    nodes = {20: Node(20, "MyAppMainWindow", "我的应用")}
    resolver, _ = resolver_for(nodes, 20, raise_on_parent={20})
    r = resolver.resolve(coord)
    record("父链查询异常时安全失败", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 8. 父窗口链成环 -> 安全失败
    nodes = {
        30: Node(30, "AppA", parent=31),
        31: Node(31, "AppB", parent=30),
    }
    resolver, _ = resolver_for(nodes, 30)
    r = resolver.resolve(coord)
    record("父链成环时安全失败", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 9. 父链超深 -> 安全失败
    nodes = {}
    for i in range(_MAX_CHAIN_DEPTH + 3):
        nodes[100 + i] = Node(100 + i, f"Deep{i}", parent=100 + i + 1)
    resolver, _ = resolver_for(nodes, 100)
    r = resolver.resolve(coord)
    record("父链超深时安全失败", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 10. 坐标转换失败必须拒绝（模拟 api 抛异常）
    class ConversionFailApi(MockWindowApi):
        def screen_to_client(self, hwnd, x, y):
            raise RuntimeError("模拟 ScreenToClient 失败")

    api = ConversionFailApi({40: Node(40, "MyApp", "应用")}, 40)
    resolver = WindowResolver(CoordinateMapper(api=api), api=api)
    r = resolver.resolve(coord)
    record("坐标转换失败时拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    # 11. 命中自身 Overlay 拒绝
    nodes = {50: Node(50, "OverlayQtClass", "VirtualMouse Overlay")}
    resolver, _ = resolver_for(nodes, 50)
    r = resolver.resolve(coord)
    record("命中自身 Overlay 拒绝", bool(r.reject_reason),
           f"reason={r.reject_reason}")

    lines = [
        "# Phase 1.1：窗口解析安全测试报告（Mock 窗口树）",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += [
        "",
        "全部用例使用模拟窗口树，没有点击桌面图标，也没有调用任何输入 API。",
        "",
    ]
    (REPORT_DIR / "phase11_resolver_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n窗口解析安全测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
