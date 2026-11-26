# 阶段 2：虚拟圆点运行时测试报告

- DPI 感知设置：PER_MONITOR_DPI_AWARE
- Qt 版本：见 env_check
- EXSTYLE：0x080800A8

| 验证项 | 结果 | 说明 |
| --- | --- | --- |
| 窗口标志 WS_EX_TRANSPARENT | 通过 | EXSTYLE=0x080800A8 bit=ON |
| 窗口标志 WS_EX_NOACTIVATE | 通过 | EXSTYLE=0x080800A8 bit=ON |
| 窗口标志 WS_EX_LAYERED | 通过 | EXSTYLE=0x080800A8 bit=ON |
| 窗口标志 WS_EX_TOOLWINDOW | 通过 | EXSTYLE=0x080800A8 bit=ON |
| 窗口标志 WS_EX_TOPMOST | 通过 | EXSTYLE=0x080800A8 bit=ON |
| Overlay 不抢前台焦点 | 通过 | show 前 HWND=0x81E44，show 后 HWND=0x81E44 |
| 圆点移动到 (300, 300) | 通过 | 实测中心=(300, 300)，期望=(300, 300) |
| 圆点移动到 (1200, 700) | 通过 | 实测中心=(1200, 700)，期望=(1200, 700) |
| 圆点移动到 (3000, 300) | 通过 | 实测中心=(3000, 300)，期望=(3000, 300) |
| 圆点移动到 (4000, 900) | 通过 | 实测中心=(4000, 900)，期望=(4000, 900) |
| 圆点移动到 (3000, -40) | 通过 | 实测中心=(3000, -40)，期望=(3000, -40) |
| 鼠标穿透 WindowFromPoint | 通过 | Overlay HWND=0xA1E12，命中 HWND=0x2512BE class='RichEditD2DPT' title='' |
| 真实鼠标未被移动（连续 12 次移动圆点） | 通过 | 对照组 (317, 334)->(317, 334) 变化=False；实验组 (317, 334)->(317, 334) 变化=False；本程序未移动光标 |
| 显示/隐藏 | 通过 | 隐藏成功=True，重新显示成功=True |
| 测试截图 | 通过 | phase2_dot_primary.png, phase2_dot_secondary.png |

## 结论

圆点可独立移动到主屏/副屏/负 Y 坐标，中心坐标与指定桌面坐标一致；鼠标穿透、不抢焦点、真实鼠标不移动均已实测。本阶段**未实现也未发送任何点击**。
