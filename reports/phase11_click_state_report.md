# Phase 1.1：点击消息状态管理测试报告（Mock PostMessage）

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 三条消息全部成功 -> COMPLETE_QUEUED | 通过 | status=complete_queued ids=['0x200', '0x201', '0x202'] |
| 完整入队仍标记为实际点击未验证 | 通过 | 未验证（仅确认消息入队；实际点击需外部证据） |
| MOUSEMOVE 失败 -> 停止且不发 DOWN/UP | 通过 | status=mousemove_failed ids=['0x200'] |
| DOWN 失败 -> 不发正常 UP | 通过 | status=down_failed ids=['0x200', '0x201'] |
| UP 失败 -> UP_FAILED 且补发释放到原 HWND | 通过 | status=up_failed ids=['0x200', '0x201', '0x202', '0x202'] |
| UP 失败 -> 保留未释放状态与补救结果 | 通过 | uncertain=True recovery=MessageResult(message_id=514, message_name='WM_LBUTTONUP', hwnd=4660, client_x=100, client_y=200, wparam=0, posted=True, last_error=0, attempt='release_recovery') |
| DOWN 后 HWND 销毁 -> 不再发 UP / 不切换窗口 | 通过 | status=up_failed ids=['0x200', '0x201'] checks=['发送前: HWND=0x1234 valid=True', 'WM_LBUTTONDOWN 前: HWND=0x1234 valid=True', 'WM_LBUTTONUP 前: HWND=0x1234 valid=False'] |
| HWND 销毁 -> 明确报告无法保证释放且无补救 | 通过 | errors=['WM_LBUTTONUP 前目标 HWND 已失效；DOWN 已入队，无法向原目标补发释放，不能保证按键已释放'] |
| 发送前 HWND 失效 -> TARGET_INVALID 且零消息 | 通过 | status=target_invalid calls=0 |
| 拒绝目标 -> REJECTED_TARGET 且零消息 | 通过 | status=rejected_target calls=0 |
| LPARAM 越界 -> LPARAM_OUT_OF_RANGE 且零消息 | 通过 | status=lparam_out_of_range calls=0 |
| 补救释放失败 -> 仍为 UP_FAILED 且保留原因 | 通过 | status=up_failed recovery=[release_recovery] WM_LBUTTONUP HWND=0x1234 client=(100, 200) wParam=0x0 -> 入队失败(GetLastError=5) errors=['WM_LBUTTONUP 入队失败 GetLastError=5；DOWN 已入队，当前可能存在未释放的左键按下状态', '补发释放消息仍失败 GetLastError=5；按键释放状态无法保证'] |

所有失败分支均通过注入的 post_fn / is_window_fn 模拟，未产生真实点击。
