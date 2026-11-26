"""Phase 1.1：坐标与 DPI 安全边界测试。

运行：
    python tests/test_coordinate_boundaries.py

覆盖：
- LPARAM 16 位有符号边界：-32768 / -32767 / 32767 / 越界
- 双屏负 Y 坐标
- DesktopCoordinate 拒绝非整数
- DPI Awareness 实际状态报告（不冒充 PM aware）
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
    DesktopCoordinate,
    current_dpi_mode,
    enable_per_monitor_dpi_awareness,
    make_lparam,
    query_actual_dpi_awareness,
    unpack_lparam,
)

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_coordinate.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


def main() -> int:
    # 1. 边界内坐标往返
    cases = [
        (-32768, -32768),
        (-32767, 32767),
        (0, 0),
        (32767, -1),
        (3000, -40),   # 副屏负 Y
        (-200, 900),
    ]
    ok = True
    details = []
    for x, y in cases:
        try:
            value = make_lparam(x, y)
            got = unpack_lparam(value)
            pair_ok = got == (x, y)
        except Exception as exc:
            pair_ok = False
            got = f"异常 {exc}"
        ok = ok and pair_ok
        details.append(f"({x},{y})->{got}")
    record("LPARAM 边界内坐标往返", ok, "; ".join(details))

    # 2. 越界坐标必须拒绝
    out_of_range = [(32768, 0), (-32769, 0), (0, 32768), (0, -32769), (40000, -40000)]
    ok = True
    for x, y in out_of_range:
        try:
            make_lparam(x, y)
            ok = False
        except ValueError:
            pass
    record("LPARAM 越界坐标全部拒绝", ok, f"越界用例={out_of_range}")

    # 3. DesktopCoordinate 负数与类型检查
    c = DesktopCoordinate(3000, -40)
    record("DesktopCoordinate 支持负 Y", (c.x, c.y) == (3000, -40), str(c))
    ok = True
    for bad in (1.5, "100", True):
        try:
            DesktopCoordinate(bad, 0)
            ok = False
        except TypeError:
            pass
    record("DesktopCoordinate 拒绝非整数", ok, "float/str/bool 均拒绝")

    # 4. DPI awareness 实际状态与报告一致
    note = enable_per_monitor_dpi_awareness()
    actual = query_actual_dpi_awareness()
    mode_text = current_dpi_mode()
    if actual is None:
        # 无法查询时，只要不冒充 PM aware 即可接受。
        ok = DpiAwareness.PER_MONITOR_AWARE not in mode_text or note.endswith("DPI_AWARE")
    else:
        expected = {
            DpiAwareness.UNAWARE: "DPI_UNAWARE",
            DpiAwareness.SYSTEM_AWARE: "SYSTEM_DPI_AWARE",
            DpiAwareness.PER_MONITOR_AWARE: "PER_MONITOR_DPI_AWARE",
        }[actual]
        ok = expected in mode_text and expected in note
    record("DPI 感知报告与实际状态一致", ok,
           f"note={note} actual={actual} current={mode_text}")

    lines = [
        "# Phase 1.1：坐标与 DPI 安全边界测试报告",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += [
        "",
        "未替换为 PER_MONITOR_AWARE_V2；仅在调用失败时查询系统实际状态，避免误报。",
        "",
    ]
    (REPORT_DIR / "phase11_coordinate_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n坐标边界测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
