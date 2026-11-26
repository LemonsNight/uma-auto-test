"""Phase 1.1 Review Fix：RealChildWindowFromPoint 坐标系测试。

运行：
    python tests/test_real_child_coordinates.py

覆盖：
- 父窗口位于屏幕非零坐标，客户区坐标必须偏移
- 传给 RealChildWindowFromPoint 的是客户区坐标
- 子窗口 GetWindowRect 校验仍使用屏幕坐标
- 坐标转换失败时不调用 RealChildWindowFromPoint，也不静默回退到根窗口
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
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_review_coords.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


class Node:
    def __init__(self, hwnd, cls, title="", parent=0, rect=(0, 0, 100, 100),
                 client=(0, 0, 100, 100), origin=(0, 0)):
        self.hwnd, self.cls, self.title = hwnd, cls, title
        self.parent, self.rect = parent, rect
        self.client, self.origin = client, origin


class CoordMockApi(WindowApi):
    """root 窗口原点不在 (0,0)，用于检验坐标转换。"""

    def __init__(self, nodes, hit, *, fail_root_conversion=False):
        self.nodes = nodes
        self.hit = hit
        self.fail_root_conversion = fail_root_conversion
        self.real_child_calls: list[tuple[int, int, int]] = []
        self.screen_to_client_calls: list[tuple[int, int, int]] = []
        self.get_rect_calls: list[int] = []

    def window_from_point(self, x, y):
        return self.hit

    def is_window(self, hwnd):
        return hwnd in self.nodes

    def is_window_enabled(self, hwnd):
        return True

    def get_class_name(self, hwnd):
        return self.nodes.get(hwnd).cls if hwnd in self.nodes else ""

    def get_window_text(self, hwnd):
        return self.nodes.get(hwnd).title if hwnd in self.nodes else ""

    def get_parent(self, hwnd):
        node = self.nodes.get(hwnd)
        return node.parent if node else 0

    def get_ancestor(self, hwnd, flag):
        return self.hit  # 命中窗口就是 root（顶层）

    def get_window_rect(self, hwnd):
        self.get_rect_calls.append(hwnd)
        return self.nodes.get(hwnd).rect if hwnd in self.nodes else (0, 0, 0, 0)

    def get_client_rect(self, hwnd):
        return self.nodes.get(hwnd).client if hwnd in self.nodes else (0, 0, 0, 0)

    def screen_to_client(self, hwnd, x, y):
        self.screen_to_client_calls.append((hwnd, x, y))
        if hwnd == self.hit and self.fail_root_conversion:
            raise RuntimeError("模拟 root 客户区转换失败")
        node = self.nodes.get(hwnd)
        if not node:
            raise RuntimeError("未知 HWND")
        ox, oy = node.origin
        return x - ox, y - oy

    def real_child_window_from_point(self, hwnd, client_x, client_y):
        self.real_child_calls.append((hwnd, client_x, client_y))
        return self.child_hwnd if hasattr(self, "child_hwnd") else 0


def main() -> int:
    # root 屏幕原点 (300, 200)；桌面坐标 (350, 260) -> 客户区 (50, 60)
    root = Node(1, "MyApp", "主窗口", rect=(300, 200, 900, 700),
                client=(0, 0, 600, 500), origin=(300, 200))
    child = Node(2, "ChildClass", "子窗口", parent=1,
                 rect=(330, 230, 500, 400), client=(0, 0, 170, 170),
                 origin=(330, 230))

    api = CoordMockApi({1: root, 2: child}, 1)
    api.child_hwnd = 2
    resolver = WindowResolver(CoordinateMapper(api=api), api=api)
    coord = DesktopCoordinate(350, 260)
    r = resolver.resolve(coord)

    record("客户区坐标转换被调用且使用桌面坐标",
           (1, 350, 260) in api.screen_to_client_calls,
           f"calls={api.screen_to_client_calls}")
    record("RealChildWindowFromPoint 收到客户区坐标",
           api.real_child_calls == [(1, 50, 60)],
           f"calls={api.real_child_calls}（期望 [(1,50,60)]）")
    record("子窗口 GetWindowRect 仍被查询（屏幕坐标校验）",
           2 in api.get_rect_calls,
           f"get_rect_calls={api.get_rect_calls}")
    record("解析到正确子窗口", r.hwnd == 2 and not r.reject_reason,
           f"target=0x{r.hwnd:X} reject={r.reject_reason}")

    # 坐标转换失败：不调用 RealChild，也不静默回退到根窗口目标
    api2 = CoordMockApi({1: root, 2: child}, 1, fail_root_conversion=True)
    api2.child_hwnd = 2
    resolver2 = WindowResolver(CoordinateMapper(api=api2), api=api2)
    r2 = resolver2.resolve(coord)
    record("转换失败时不调用 RealChildWindowFromPoint",
           len(api2.real_child_calls) == 0,
           f"calls={api2.real_child_calls}")
    record("转换失败时拒绝而不是回退到根窗口",
           bool(r2.reject_reason) and not r2.is_safe_target,
           f"target=0x{r2.hwnd:X} reject={r2.reject_reason}")

    lines = [
        "# Phase 1.1 Review Fix：RealChildWindowFromPoint 坐标系测试报告",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += ["", "全部使用模拟窗口树，未点击任何真实窗口。", ""]
    (REPORT_DIR / "phase11_review_coords_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\nRealChild 坐标测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
