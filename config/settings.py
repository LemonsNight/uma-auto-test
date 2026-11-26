"""集中配置：颜色、尺寸、快捷键、日志格式。

本文件只存放常量，不包含任何输入逻辑。
"""

from __future__ import annotations

# ---- Overlay 外观 ----
DOT_RADIUS_PX = 9              # 圆点半径（物理像素）
DOT_OUTLINE_PX = 2
DOT_COLOR = (222, 48, 48)      # 默认红色 (R, G, B)
DOT_FLASH_COLOR = (255, 205, 40)  # 点击反馈：金黄色
DOT_FLASH_RADIUS_PX = 14
CLICK_FEEDBACK_MS = 180        # 点击反馈持续时间
WINDOW_SIZE_PX = 48            # Overlay 窗口逻辑尺寸（留出光晕空间）

# ---- 全局紧急停止 ----
# 使用 RegisterHotKey 注册组合键，不劫持单键，不影响普通输入。
HOTKEY_MODIFIERS = 0x0002 | 0x0004 | 0x0008  # MOD_CONTROL | MOD_ALT | MOD_SHIFT
HOTKEY_VK = 0x4B  # VK_K -> Ctrl+Alt+Shift+K
HOTKEY_LABEL = "Ctrl+Alt+Shift+K"

# ---- 日志 ----
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILENAME = "virtualmouse.log"

# ---- 状态文本 ----
STATE_LABELS = {
    "idle": "空闲（未启动）",
    "running": "运行中",
    "paused": "已暂停",
    "stopped": "已紧急停止（需复位）",
}
