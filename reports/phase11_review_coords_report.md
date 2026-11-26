# Phase 1.1 Review Fix：RealChildWindowFromPoint 坐标系测试报告

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 客户区坐标转换被调用且使用桌面坐标 | 通过 | calls=[(1, 350, 260), (2, 350, 260)] |
| RealChildWindowFromPoint 收到客户区坐标 | 通过 | calls=[(1, 50, 60)]（期望 [(1,50,60)]） |
| 子窗口 GetWindowRect 仍被查询（屏幕坐标校验） | 通过 | get_rect_calls=[2] |
| 解析到正确子窗口 | 通过 | target=0x2 reject=None |
| 转换失败时不调用 RealChildWindowFromPoint | 通过 | calls=[] |
| 转换失败时拒绝而不是回退到根窗口 | 通过 | target=0x1 reject=root 窗口客户区坐标转换失败，无法安全定位子窗口，拒绝按根窗口目标继续发送 |

全部使用模拟窗口树，未点击任何真实窗口。
