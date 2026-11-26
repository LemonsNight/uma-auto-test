# 阶段 5：记事本点击测试报告

说明：`入队` 仅表示 PostMessage 成功；`实际点击` 由记事本 RichEditD2DPT 插入符变化独立验证。两者严格区分。

| 测试项 | 消息入队成功 | 实际点击验证成功 | 说明 |
| --- | --- | --- | --- |
| 记事本前台点击 | 是 | 是 | 坐标=(126, 215) 圆点中心=(126, 215) 目标=HWND 0x2512BE class='RichEditD2DPT' title='' 入队=True 插入符 (0, 0)->(44, 44) 实际点击=True |
| 圆点位置与点击坐标一致（前台） | — | — | 圆点中心=(126, 215) 点击坐标=(126, 215) 一致=True |
| 记事本被部分遮挡时点击 | 是 | 是 | 坐标=(126, 250) 圆点中心=(126, 250) 目标=HWND 0x2512BE class='RichEditD2DPT' title='' 入队=True 插入符 (0, 0)->(44, 44) 实际点击=True |
| 遮挡时前台确实不是记事本 | — | — | 遮挡窗口 HWND=0x8418B0 切换后前台=0x8418B0 遮挡期间前台=0x8418B0 记事本=0x3511E0 成立=True |
| 遮挡点击未改变前台窗口 | — | — | 遮挡后前台=0x8418B0 点击后前台=0x8418B0 一致=True |
| 记事本最小化时的行为 | — | — | IsIconic=True 最小化后窗口矩形=(-32000, -32000, -31840, -31972)；原坐标 (126, 215) 解析为 HWND=0x20CBE class='SysListView32'（不是记事本）；本程序按桌面坐标工作，无法向已最小化的记事本目标区域发送点击，且拒绝向系统桌面窗口发送。 |
| 浏览器已置于前台（前置条件） | — | — | 浏览器 HWND=0x4027C title='数字乡村平台 - 测试环境 - Google Chrome' 切换后前台=0x4027C 成功=True |
| 浏览器前台时对记事本点击 | 是 | 是 | 坐标=(2799, 362) 圆点中心=(2799, 362) 目标=HWND 0x2512BE class='RichEditD2DPT' title='' 入队=True 插入符 (0, 0)->(43, 43) 实际点击=True |
| 真实鼠标未被移动（对照组 + 点击前后采样） | — | — | 对照组 (1461, 1421)->(1461, 1421) 变化=False；实验组 (1461, 1421)->(1461, 1421) 变化=False；本程序未移动光标 |
| 前台窗口未被 PostMessage 抢走 | — | — | 点击前前台=0x4027C 点击后前台=0x41B38 一致=False（浏览器前置条件成立） |
| 紧急停止后立即拒绝后续点击 | — | — | state=stopped 返回值=None |

## 测试环境

- 记事本：Windows 11 内置现代记事本（顶层类 `Notepad`，文本区子窗口 `RichEditD2DPT`）
- 插入符读取：`EM_GETSEL`（SendMessage 仅用于测试验证，不是点击手段）
- 点击发送：`PostMessageW` WM_MOUSEMOVE / WM_LBUTTONDOWN / WM_LBUTTONUP

## 截图

- `screenshots/phase5_foreground_click.png`
- `screenshots/phase5_background_click.png`
- `screenshots/phase5_minimized.png`
