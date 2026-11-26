# 阶段 3/4：输入模块、状态机与热键测试报告

| 验证项 | 结果 | 说明 |
| --- | --- | --- |
| LPARAM 编解码（含负坐标） | 通过 | 4 组坐标往返一致 |
| LPARAM 越界拒绝 | 通过 | 超出 16 位有符号范围时抛出 ValueError |
| 禁用输入 API 静态检查 | 通过 | 命中=[] |
| WindowFromPoint 解析到测试窗口 | 通过 | HWND=0x31DD8 class='Qt6120QWindowIcon' title='PostMessage Test Target' client=(159, 99) reject=None |
| PostMessage 三条消息顺序与 wParam | 通过 | ids=['0x200', '0x201', '0x202'] wparams=['0x0', '0x1', '0x0'] |
| PostMessage 全部入队成功 | 通过 | 点击 (199, 999) -> HWND=0x31DD8 class='Qt6120QWindowIcon' title='PostMessage Test Target' client=(159, 99) /   消息入队: 全部成功 /     WM_MOUSEMOVE HWND=0x31DD8 client=(159, 99) wParam=0x0 -> 入队成功 /     WM_LBUTTONDOWN HWND=0x31DD8 client=(159, 99) wParam=0x1 -> 入队成功 /     WM_LBUTTONUP HWND=0x31DD8 client=(159, 99) wParam=0x0 -> 入队成功 /   实际点击验证: 未验证（仅确认消息入队；实际点击需外部证据） |
| 入队成功与实际验证严格区分 | 通过 | 未验证（仅确认消息入队；实际点击需外部证据） |
| 拒绝向系统桌面窗口发送点击 | 通过 | reason=系统桌面窗口 class='Progman'，禁止发送模拟点击 |
| 启动后状态 running | 通过 | running |
| 暂停时拒绝点击 | 通过 | state=paused |
| 恢复后允许点击 | 通过 | state=running |
| 紧急停止立即拒绝点击与移动 | 通过 | state=stopped click=None move=False |
| 复位后恢复运行 | 通过 | running |
| 全局热键注册 | 通过 | label=Ctrl+Alt+Shift+K registered=True |
| 全局热键触发紧急停止 | 通过 | 模拟投递=True state=stopped |

## 关键语义

- PostMessage 返回 True 仅代表消息入队，不代表目标程序处理了点击。
- 本测试中的目标窗口是测试用 QLabel，不是业务程序。
