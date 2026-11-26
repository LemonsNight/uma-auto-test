# VirtualMouse Phase 1 — Windows 独立虚拟鼠标 PoC

一个只使用 `PostMessage` 发送鼠标消息的 Windows 虚拟鼠标 PoC。
**不移动真实鼠标**，真实鼠标可同时正常操作其它软件。

## 目标与范围

本阶段只实现通用桌面能力：独立圆点、按桌面坐标移动、按桌面坐标单击、暂停/恢复/紧急停止。
**不包含赛马娘业务自动化。**

## 环境（实测）

- Windows 11 Home China 25H2，build 26200.9974
- Python 3.13.5（`D:\app\python\python.exe`）
- PySide6 6.12.0 / Qt 6.12.0
- pywin32（可用）
- 双显示器：主屏 2560×1440 @100%，副屏 2560×1600 @150%，副屏 Y 起点为 -87
- 进程 DPI 感知：`PER_MONITOR_DPI_AWARE`

> 默认 `python` 命令指向 WorkBuddy 内置 Python，没有安装依赖。
> 请使用 `D:\app\python\python.exe` 运行本项目。

## 运行

```bash
cd D:/app/PYAPP/4v-uma/VirtualMouse
D:/app/python/python.exe main.py
```

控制面板功能：
- X / Y：物理桌面坐标（支持副屏与负数）
- 移动圆点 / 单击
- 显示 / 隐藏圆点
- 暂停 / 恢复（暂停时点击被拒绝，仍可手动移动圆点）
- 紧急停止（立即拒绝所有后续点击与移动，需"复位"恢复）
- 全局紧急停止热键：`Ctrl+Alt+Shift+K`
- 当前状态、最近一次点击结果、最近操作日志

## 严格约束

点击唯一路径：

```
WindowFromPoint ->（必要时）子窗口 -> ScreenToClient
-> PostMessage(WM_MOUSEMOVE) -> PostMessage(WM_LBUTTONDOWN)
-> PostMessage(WM_LBUTTONUP)
```

代码中不存在也不允许出现：
`SetCursorPos` / `SendInput` / `mouse_event` / `pyautogui.*` / 任何移动真实鼠标的兜底方案。
不安装驱动，不尝试绕过 UIPI 或安全机制。

**重要语义**：`PostMessage` 返回 `True` 只表示消息成功入队，
**不代表目标程序处理了点击**，更不代表业务动作成功。
日志与 UI 中始终将"入队成功"和"实际点击验证"分开记录。

## 目录结构

```
VirtualMouse/
├── main.py                     # 程序入口，装配各模块
├── requirements.txt
├── README.md
├── config/
│   └── settings.py             # 颜色、尺寸、热键、日志等常量
├── core/
│   ├── coordinate.py           # DesktopCoordinate、DPI 感知、LPARAM 编解码
│   ├── window_resolver.py      # WindowResolver / CoordinateMapper
│   ├── input_backend.py        # PostMessageBackend（唯一点击路径）
│   ├── virtual_cursor.py       # VirtualCursorController 状态机
│   └── hotkey.py               # 全局紧急停止热键
├── overlay/
│   ├── overlay_window.py       # 透明、置顶、鼠标穿透 Overlay
│   └── cursor_renderer.py      # 圆点绘制与点击反馈
├── ui/
│   └── main_window.py          # 控制面板
├── tools/                      # 环境诊断/截图/探测脚本
├── tests/                      # 各阶段运行时测试
└── reports/                    # 测试报告与截图
```

## 实测得到的关键技术点

1. **Qt 的 `move()` 在混合 DPI 下不可靠**：`move(3000, 100)` 实际落在物理坐标 `(3220, 194)`。
   因此圆点定位使用 Win32 `SetWindowPos`（物理像素），并二次读取 `GetWindowRect` 校验中心点。
2. 透明/穿透标志经实测生效：`WS_EX_TRANSPARENT`、`WS_EX_NOACTIVATE`、
   `WS_EX_LAYERED`、`WS_EX_TOOLWINDOW`、`WS_EX_TOPMOST` 均为 ON。
3. `WindowFromPoint` 会穿透 Overlay 命中下层窗口；Overlay 不改变前台窗口与光标位置。
4. 现代记事本的文本区是 `RichEditD2DPT` 子窗口，可用 `EM_GETSEL` 插入符变化独立验证点击是否真的被处理。
5. `WindowFromPoint` 返回的命中窗口通常就是应接收鼠标消息的子窗口；
   只有在它返回顶层窗口时才用 `RealChildWindowFromPoint` 进一步定位。

## 测试命令

```bash
D:/app/python/python.exe tools/env_check.py
D:/app/python/python.exe tests/test_overlay_runtime.py
D:/app/python/python.exe tests/test_input_module.py
D:/app/python/python.exe tests/test_notepad_runtime.py
D:/app/python/python.exe tests/test_mouse_isolation.py
D:/app/python/python.exe tests/smoke_test_main.py
```

汇总报告见 `reports/TEST_REPORT.md`，已知限制见 `reports/KNOWN_LIMITATIONS.md`。
