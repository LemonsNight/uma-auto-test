"""窗口解析与客户区坐标映射。

全部基于 WindowFromPoint /（必要时）RealChildWindowFromPoint / ScreenToClient，
不触碰真实鼠标。

Phase 1.1 安全加固：
- 通过可注入的 WindowApi 包装 Win32 查询，便于用模拟窗口树做单元测试。
- 解析目标时沿 GetParent 走完整父窗口链；只要链上出现 Progman / WorkerW /
  SHELLDLL_DefView，或标题 "Program Manager"，即判定为系统桌面并拒绝。
- SysListView32 不按类名全局拒绝；只有其祖先链包含桌面结构时才拒绝。
- 父窗口链遍历异常、成环或超过深度上限时采用安全失败（拒绝）策略。
- 坐标转换失败不再静默沿用屏幕坐标，而是拒绝发送。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass, field

import win32con
import win32gui

from .coordinate import DesktopCoordinate

logger = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RealChildWindowFromPoint.argtypes = [wintypes.HWND, wintypes.POINT]
_user32.RealChildWindowFromPoint.restype = wintypes.HWND

# 系统桌面相关窗口类：链上出现即拒绝。
_DESKTOP_ROOT_CLASSES = {"Progman", "WorkerW"}
_DESKTOP_VIEW_CLASSES = {"SHELLDLL_DefView"}
_DESKTOP_TITLE = "Program Manager"
_MAX_CHAIN_DEPTH = 32

# 已知可能受 UIPI / 系统保护限制的窗口类，只报告限制，不尝试绕过。
_RESTRICTED_CLASS_PREFIXES = (
    "Windows.UI.",
    "Windows.UI.Core",
    "ApplicationFrameWindow",
    "Chrome_WidgetWin",
)
_RESTRICTED_CLASS_EXACT = {"Shell_TrayWnd", "Progman"}


class WindowApi:
    """Win32 窗口查询的薄包装；测试可替换为模拟实现。

    只包含只读查询，不含任何输入发送能力。
    """

    def window_from_point(self, x: int, y: int) -> int:
        return int(win32gui.WindowFromPoint((x, y)))

    def real_child_window_from_point(self, hwnd: int, client_x: int, client_y: int) -> int:
        """RealChildWindowFromPoint 使用 hwnd 的**客户区坐标**，不是屏幕坐标。

        调用方必须先用 ScreenToClient 把桌面坐标转换成该窗口的客户区坐标。
        """
        raw = _user32.RealChildWindowFromPoint(
            wintypes.HWND(hwnd), wintypes.POINT(client_x, client_y)
        )
        return int(raw) if raw else 0

    def get_parent(self, hwnd: int) -> int:
        return int(win32gui.GetParent(hwnd))

    def get_ancestor(self, hwnd: int, flag: int) -> int:
        return int(win32gui.GetAncestor(hwnd, flag))

    def get_class_name(self, hwnd: int) -> str:
        return win32gui.GetClassName(hwnd)

    def get_window_text(self, hwnd: int) -> str:
        return win32gui.GetWindowText(hwnd)

    def is_window(self, hwnd: int) -> bool:
        return bool(win32gui.IsWindow(hwnd))

    def is_window_enabled(self, hwnd: int) -> bool:
        return bool(win32gui.IsWindowEnabled(hwnd))

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return tuple(int(v) for v in win32gui.GetWindowRect(hwnd))

    def screen_to_client(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        cx, cy = win32gui.ScreenToClient(hwnd, (x, y))
        return int(cx), int(cy)

    def get_client_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return tuple(int(v) for v in win32gui.GetClientRect(hwnd))


@dataclass
class ChainNode:
    hwnd: int
    class_name: str
    title: str
    title_read_failed: bool = False

    def describe(self) -> str:
        suffix = " title读取失败" if self.title_read_failed else ""
        return f"0x{self.hwnd:X}[{self.class_name!r},{self.title!r}]{suffix}"


@dataclass
class ResolvedTarget:
    """一次坐标解析的结果。"""

    hwnd: int
    title: str
    class_name: str
    client_x: int
    client_y: int
    root_hwnd: int
    root_title: str
    is_child_window: bool = False
    reject_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    chain: list[ChainNode] = field(default_factory=list)
    chain_reliable: bool = True

    @property
    def is_safe_target(self) -> bool:
        return self.reject_reason is None

    def describe(self) -> str:
        return (
            f"HWND=0x{self.hwnd:X} class={self.class_name!r} "
            f"title={self.title!r} client=({self.client_x}, {self.client_y})"
        )


class CoordinateMapper:
    """桌面坐标 -> 目标窗口客户区坐标。"""

    def __init__(self, api: WindowApi | None = None) -> None:
        self.api = api or WindowApi()

    def screen_to_client(self, hwnd: int, coord: DesktopCoordinate) -> tuple[int, int]:
        if not self.api.is_window(hwnd):
            raise ValueError(f"HWND 0x{hwnd:X} 已失效，无法转换坐标")
        return self.api.screen_to_client(hwnd, coord.x, coord.y)

    def is_in_client_area(self, hwnd: int, client_x: int, client_y: int) -> bool:
        try:
            left, top, right, bottom = self.api.get_client_rect(hwnd)
        except Exception:
            return False
        return left <= client_x < right and top <= client_y < bottom


class WindowResolver:
    """按桌面坐标定位实际接收鼠标消息的窗口。"""

    def __init__(
        self,
        mapper: CoordinateMapper | None = None,
        overlay_title: str = "VirtualMouse Overlay",
        api: WindowApi | None = None,
    ) -> None:
        self.api = api or WindowApi()
        self.mapper = mapper or CoordinateMapper(api=self.api)
        self.overlay_title = overlay_title

    def resolve(self, coord: DesktopCoordinate) -> ResolvedTarget:
        notes: list[str] = []

        try:
            hit_hwnd = self.api.window_from_point(coord.x, coord.y)
            valid_hit = bool(hit_hwnd) and bool(self.api.is_window(hit_hwnd))
        except Exception as exc:
            logger.warning("WindowFromPoint / IsWindow 查询异常: %s", exc)
            return ResolvedTarget(
                hwnd=0, title="", class_name="", client_x=coord.x, client_y=coord.y,
                root_hwnd=0, root_title="",
                reject_reason=f"WindowFromPoint / IsWindow 查询异常，安全失败: {exc}",
            )
        if not valid_hit:
            return ResolvedTarget(
                hwnd=hit_hwnd, title="", class_name="", client_x=coord.x, client_y=coord.y,
                root_hwnd=0, root_title="",
                reject_reason="WindowFromPoint 未返回有效窗口",
            )

        hit_title = self._safe_window_text(hit_hwnd)
        hit_class = self._safe_class_name(hit_hwnd)
        if hit_title == self.overlay_title:
            return ResolvedTarget(
                hwnd=hit_hwnd, title=hit_title, class_name=hit_class,
                client_x=coord.x, client_y=coord.y,
                root_hwnd=hit_hwnd, root_title=hit_title,
                reject_reason="命中 VirtualMouse 自身 Overlay（穿透失效？），拒绝发送",
            )

        root_hwnd = self.api.get_ancestor(hit_hwnd, win32con.GA_ROOT) or hit_hwnd
        root_title = self._safe_window_text(root_hwnd)

        # 命中链安全检查：在定位子窗口之前先判断命中窗口是否属于桌面。
        hit_reason = self._safety_reject_reason(hit_hwnd, "WindowFromPoint 命中")
        if hit_reason:
            chain, reliable = self._walk_chain(hit_hwnd)
            return ResolvedTarget(
                hwnd=hit_hwnd, title=hit_title, class_name=hit_class,
                client_x=coord.x, client_y=coord.y,
                root_hwnd=root_hwnd, root_title=root_title,
                reject_reason=hit_reason, chain=chain, chain_reliable=reliable,
                notes=notes,
            )

        # WindowFromPoint 本身返回的就是命中测试选定的窗口（现代记事本中
        # 是 RichEditD2DPT），通常已是实际接收鼠标消息的子窗口，应优先保留。
        # 只有当它返回顶层窗口时，才用 RealChildWindowFromPoint 进一步定位。
        target_hwnd = hit_hwnd
        is_child = hit_hwnd != root_hwnd
        root_conversion_failed = False
        if is_child:
            notes.append(
                f"WindowFromPoint 命中子窗口 HWND=0x{hit_hwnd:X} class={hit_class!r}"
            )
        else:
            # RealChildWindowFromPoint 需要 root_hwnd 的客户区坐标；
            # 转换失败时不调用 API，也不静默回退到根窗口。
            try:
                root_client_x, root_client_y = self.api.screen_to_client(
                    root_hwnd, coord.x, coord.y
                )
                notes.append(
                    f"root_hwnd=0x{root_hwnd:X} 客户区坐标=({root_client_x}, {root_client_y}) "
                    f"（屏幕坐标=({coord.x}, {coord.y})）"
                )
            except Exception as exc:
                root_conversion_failed = True
                notes.append(
                    f"root_hwnd 客户区坐标转换失败，跳过 RealChildWindowFromPoint: {exc}"
                )
                logger.warning(
                    "root HWND=0x%X 客户区坐标转换失败: %s；不会使用屏幕坐标调用 API",
                    root_hwnd, exc,
                )
            if not root_conversion_failed:
                try:
                    child = self.api.real_child_window_from_point(
                        root_hwnd, root_client_x, root_client_y
                    )
                    if child and child != root_hwnd and self.api.is_window(child):
                        child_class = self._safe_class_name(child)
                        child_title = self._safe_window_text(child)
                        # GetWindowRect 是屏幕坐标，继续用桌面坐标校验。
                        try:
                            cl, ct, cr, cb = self.api.get_window_rect(child)
                        except Exception:
                            cl = ct = cr = cb = 0
                        if (
                            cr > cl
                            and cb > ct
                            and cl <= coord.x < cr
                            and ct <= coord.y < cb
                            and child_title != self.overlay_title
                        ):
                            # 子窗口同样要做桌面链检查，不能因为父级已通过就跳过。
                            child_reason = self._safety_reject_reason(child, "候选子窗口")
                            if child_reason:
                                notes.append(f"候选子窗口被拒绝: {child_reason}")
                            else:
                                target_hwnd = child
                                is_child = True
                                notes.append(
                                    f"定位到子窗口 HWND=0x{child:X} class={child_class!r} "
                                    f"title={child_title!r}"
                                )
                except Exception as exc:
                    notes.append(f"RealChildWindowFromPoint 不可用: {exc}")

        target_title = self._safe_window_text(target_hwnd)
        target_class = self._safe_class_name(target_hwnd)
        chain, reliable = self._walk_chain(target_hwnd)

        reject_reason = self._safety_reject_reason(target_hwnd, "最终目标")
        if not reject_reason and root_conversion_failed:
            reject_reason = (
                "root 窗口客户区坐标转换失败，无法安全定位子窗口，"
                "拒绝按根窗口目标继续发送"
            )
        if not reject_reason:
            if not self.api.is_window(target_hwnd):
                reject_reason = "窗口句柄在解析过程中失效"
            elif not self.api.is_window_enabled(target_hwnd):
                reject_reason = "目标窗口被禁用（IsWindowEnabled=False），可能被系统保护"

        # 坐标转换失败必须拒绝，不能静默沿用屏幕坐标继续发送。
        try:
            client_x, client_y = self.mapper.screen_to_client(target_hwnd, coord)
        except Exception as exc:
            reject_reason = reject_reason or f"桌面坐标转客户区坐标失败: {exc}"
            notes.append(f"坐标转换失败: {exc}")
            client_x, client_y = coord.x, coord.y
        else:
            if not self.mapper.is_in_client_area(target_hwnd, client_x, client_y):
                notes.append(
                    f"转换后坐标 ({client_x}, {client_y}) 不在客户区内，"
                    "目标程序可能忽略该消息"
                )

        for prefix in _RESTRICTED_CLASS_PREFIXES:
            if target_class.startswith(prefix):
                notes.append(
                    f"窗口类 {target_class!r} 可能受 UIPI / 应用沙箱限制；"
                    "仅按实际入队结果报告，不尝试绕过"
                )
                break
        if target_class in _RESTRICTED_CLASS_EXACT:
            notes.append(f"系统窗口类 {target_class!r}，仅发送，不尝试绕过")

        result = ResolvedTarget(
            hwnd=target_hwnd,
            title=target_title,
            class_name=target_class,
            client_x=client_x,
            client_y=client_y,
            root_hwnd=root_hwnd,
            root_title=root_title,
            is_child_window=is_child,
            reject_reason=reject_reason,
            notes=notes,
            chain=chain,
            chain_reliable=reliable,
        )
        logger.info("解析坐标 %s -> %s", coord, result.describe())
        for node in chain:
            logger.debug("  链: %s", node.describe())
        for note in notes:
            logger.info("  note: %s", note)
        if reject_reason:
            logger.warning("拒绝目标: %s", reject_reason)
        return result

    # ---------- 安全判定 ----------
    def _walk_chain(self, hwnd: int) -> tuple[list[ChainNode], bool]:
        """沿 GetParent 向上遍历，返回 (链, 是否可靠)。

        安全要求（Phase 1.1 Review Fix）：
        - GetClassName 失败或返回空字符串：链不可靠（不能用空类名冒充已知类名放行）。
        - IsWindow / GetParent 抛异常或句柄失效：链不可靠。
        - 成环、超深：链不可靠。
        - GetWindowText 失败：只记录诊断标志，不替代类名安全检查。
        """
        chain: list[ChainNode] = []
        seen: set[int] = set()
        current = hwnd
        try:
            for _ in range(_MAX_CHAIN_DEPTH):
                if not current:
                    return chain, True
                if current in seen:
                    return chain, False
                seen.add(current)

                # IsWindow 查询异常或失败 -> 不可靠
                try:
                    if not self.api.is_window(current):
                        return chain, False
                except Exception as exc:
                    logger.warning("IsWindow 查询异常 HWND=0x%X: %s", current, exc)
                    return chain, False

                # GetClassName 是关键安全数据：失败/空值一律不可靠
                try:
                    class_name = self.api.get_class_name(current)
                except Exception as exc:
                    logger.warning("GetClassName 查询异常 HWND=0x%X: %s", current, exc)
                    return chain, False
                if not isinstance(class_name, str) or not class_name:
                    logger.warning("GetClassName 返回空值 HWND=0x%X，链不可靠", current)
                    return chain, False

                # 标题只是诊断信息，失败不影响类名安全判定。
                title_read_failed = False
                try:
                    title = self.api.get_window_text(current)
                    if not isinstance(title, str):
                        title = ""
                        title_read_failed = True
                except Exception as exc:
                    title = ""
                    title_read_failed = True
                    logger.debug("GetWindowText 查询异常 HWND=0x%X: %s", current, exc)

                chain.append(
                    ChainNode(
                        hwnd=current,
                        class_name=class_name,
                        title=title,
                        title_read_failed=title_read_failed,
                    )
                )

                # GetParent 查询异常 -> 不可靠
                try:
                    parent = self.api.get_parent(current)
                except Exception as exc:
                    logger.warning("GetParent 查询异常 HWND=0x%X: %s", current, exc)
                    return chain, False
                if not parent:
                    return chain, True
                current = parent
        except Exception as exc:
            logger.warning("父窗口链遍历异常 HWND=0x%X: %s", hwnd, exc)
            return chain, False
        return chain, False

    def _safety_reject_reason(self, hwnd: int, stage: str) -> str | None:
        chain, reliable = self._walk_chain(hwnd)
        if not reliable:
            return (
                f"{stage}: 父窗口链不可靠（异常/成环/超深/句柄失效），"
                "按安全失败策略拒绝发送"
            )
        classes = [node.class_name for node in chain]
        titles = [node.title for node in chain]
        if any(cls in _DESKTOP_ROOT_CLASSES for cls in classes):
            return f"{stage}: 父窗口链包含系统桌面窗口类 {sorted(_DESKTOP_ROOT_CLASSES)}，拒绝发送"
        if any(cls in _DESKTOP_VIEW_CLASSES for cls in classes):
            return f"{stage}: 父窗口链包含 SHELLDLL_DefView（桌面视图），拒绝发送"
        if _DESKTOP_TITLE in titles:
            return f"{stage}: 父窗口链包含标题 {_DESKTOP_TITLE!r}，拒绝发送"
        # SysListView32 只在确认属于桌面结构时拒绝；普通应用中的同类名不拒绝。
        target_class = classes[0] if classes else ""
        if target_class == "SysListView32" and (
            "SHELLDLL_DefView" in classes
            or any(cls in _DESKTOP_ROOT_CLASSES for cls in classes)
        ):
            return f"{stage}: 桌面图标列表 SysListView32，拒绝发送"
        return None

    @staticmethod
    def _check_reject(class_name: str, title: str, hwnd: int) -> str | None:
        """兼容旧调用的即时检查（不含父窗口链）。"""
        if class_name in _DESKTOP_ROOT_CLASSES or class_name in _DESKTOP_VIEW_CLASSES:
            return f"系统桌面窗口 class={class_name!r}，禁止发送模拟点击"
        if title == _DESKTOP_TITLE:
            return f"系统桌面窗口 title={title!r}，禁止发送模拟点击"
        if not win32gui.IsWindow(hwnd):
            return "窗口句柄在解析过程中失效"
        if not win32gui.IsWindowEnabled(hwnd):
            return "目标窗口被禁用（IsWindowEnabled=False），可能被系统保护"
        return None

    def _safe_window_text(self, hwnd: int) -> str:
        try:
            return self.api.get_window_text(hwnd)
        except Exception:
            return ""

    def _safe_class_name(self, hwnd: int) -> str:
        try:
            return self.api.get_class_name(hwnd)
        except Exception:
            return ""
