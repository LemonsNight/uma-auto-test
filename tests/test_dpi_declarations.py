"""Phase 1.1 Review Fix：DPI ctypes 声明与状态报告测试。

运行：
    python tests/test_dpi_declarations.py

覆盖：
- Win32 API 声明（HANDLE 用 c_void_p，HRESULT / BOOL 返回类型）
- 模拟设置成功、设置失败、查询成功、查询失败
- 实际状态与报告一致；UNKNOWN 不冒充 PM aware
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import (  # noqa: E402
    DpiAwareness,
    _apply_dpi_awareness,
    current_dpi_mode,
    current_dpi_mode_value,
    dpi_api_declarations,
    enable_per_monitor_dpi_awareness,
    reset_dpi_state_for_test,
)

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_review_dpi.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


def main() -> int:
    decl = dpi_api_declarations()

    # 1. HANDLE 类型（64 位安全）
    ctx = decl["GetThreadDpiAwarenessContext"]
    record("GetThreadDpiAwarenessContext 返回 HANDLE(c_void_p)",
           ctx["restype"] is wintypes.HANDLE and wintypes.HANDLE is ctypes.c_void_p,
           f"restype={ctx['restype']} argtypes={ctx['argtypes']}")

    from_ctx = decl["GetAwarenessFromDpiAwarenessContext"]
    record("GetAwarenessFromDpiAwarenessContext 参数 HANDLE + c_int 返回",
           from_ctx["argtypes"] == [wintypes.HANDLE]
           and from_ctx["restype"] is ctypes.c_int,
           f"argtypes={from_ctx['argtypes']} restype={from_ctx['restype']}")

    # 2. shcore 声明
    get_p = decl["GetProcessDpiAwareness"]
    set_p = decl["SetProcessDpiAwareness"]
    record("GetProcessDpiAwareness 参数/返回类型",
           get_p["restype"] is ctypes.HRESULT
           and len(get_p["argtypes"]) == 2
           and get_p["argtypes"][0] is wintypes.HANDLE
           and get_p["argtypes"][1] is ctypes.POINTER(ctypes.c_int),
           f"argtypes={get_p['argtypes']} restype={get_p['restype']}")
    record("SetProcessDpiAwareness 参数/返回类型",
           set_p["restype"] is ctypes.HRESULT
           and set_p["argtypes"] == [ctypes.c_int],
           f"argtypes={set_p['argtypes']} restype={set_p['restype']}")

    set_legacy = decl["SetProcessDPIAware"]
    record("SetProcessDPIAware 返回 BOOL",
           set_legacy["restype"] is wintypes.BOOL,
           f"restype={set_legacy['restype']}")

    # 3. 模拟分支
    mode = _apply_dpi_awareness(lambda: True, lambda: True,
                                lambda: DpiAwareness.PER_MONITOR_AWARE)
    record("设置成功 + 查询成功 PM -> PM", mode == DpiAwareness.PER_MONITOR_AWARE,
           f"mode={mode}")

    mode = _apply_dpi_awareness(lambda: False, lambda: True,
                                lambda: DpiAwareness.SYSTEM_AWARE)
    record("PM 设置失败 + 系统设置成功 + 查询 SYSTEM -> SYSTEM",
           mode == DpiAwareness.SYSTEM_AWARE, f"mode={mode}")

    mode = _apply_dpi_awareness(lambda: False, lambda: False,
                                lambda: DpiAwareness.UNAWARE)
    record("设置失败 + 查询 UNAWARE -> UNAWARE", mode == DpiAwareness.UNAWARE,
           f"mode={mode}")

    mode = _apply_dpi_awareness(lambda: True, lambda: True,
                                lambda: None)
    record("查询失败 -> UNKNOWN（不冒充 PM）", mode == DpiAwareness.UNKNOWN,
           f"mode={mode} label={core_label(mode)}")

    def raising_query():
        raise RuntimeError("模拟查询异常")

    mode = _apply_dpi_awareness(lambda: True, lambda: True, raising_query)
    record("查询抛异常 -> UNKNOWN", mode == DpiAwareness.UNKNOWN, f"mode={mode}")

    # 4. 真实进程状态与报告一致
    reset_dpi_state_for_test()
    note = enable_per_monitor_dpi_awareness()
    label = current_dpi_mode()
    value = current_dpi_mode_value()
    record("实际状态与报告一致",
           (value == DpiAwareness.PER_MONITOR_AWARE and "PER_MONITOR_DPI_AWARE" in note
            and "PER_MONITOR_DPI_AWARE" in label)
           or (value == DpiAwareness.UNKNOWN and "UNKNOWN" in note),
           f"note={note} value={value} label={label}")

    lines = [
        "# Phase 1.1 Review Fix：DPI ctypes 声明与状态测试报告",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += ["", "未引入 PER_MONITOR_AWARE_V2；保留现有 PM v1 方案。", ""]
    (REPORT_DIR / "phase11_review_dpi_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\nDPI 声明测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


def core_label(mode: int) -> str:
    from core.coordinate import _dpi_mode_label
    return _dpi_mode_label(mode)


if __name__ == "__main__":
    raise SystemExit(main())
