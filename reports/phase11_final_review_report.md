# Phase 1.1 Final Review：最后安全性修复测试报告

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| GetAncestor 异常 -> 拒绝且 chain_reliable=False | 通过 | reason=GetAncestor 查询异常，安全失败: 模拟 GetAncestor 异常 reliable=False |
| GetAncestor 异常 -> 未把 hit_hwnd 当成 root | 通过 | root=0x0 hit=0x1 |
| GetAncestor 异常 -> resolve 不抛出未处理异常 | 通过 | 调用正常返回 ResolvedTarget |
| GetAncestor 异常 -> 后端不发送 PostMessage | 通过 | post_calls=0 status=rejected_target |
| GetAncestor 返回无效 HWND -> 拒绝 | 通过 | reason=GetAncestor 未返回有效窗口，安全失败 |
| 普通应用正常子窗口继续放行 | 通过 | target=0xB reject=None |
| 候选子窗口属于桌面结构 -> 拒绝不回退根 | 通过 | target=0x16 reason=候选子窗口: 父窗口链包含 SHELLDLL_DefView（桌面视图），拒绝发送 |
| 桌面候选子窗口 -> 后端不发送 | 通过 | post_calls=0 |
| 候选子窗口父链异常 -> 拒绝 | 通过 | reason=候选子窗口: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 |
| 候选子窗口父链异常 -> 后端不发送 | 通过 | post_calls=0 |
| 候选子窗口 HWND 失效 -> 拒绝 | 通过 | reason=候选子窗口 HWND=0xB 已失效 |
| 候选子窗口失效 -> 后端不发送 | 通过 | post_calls=0 |
| 候选子窗口 GetClassName 异常 -> 拒绝 | 通过 | reason=候选子窗口: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 |
| 进程级查询成功 -> source=process | 通过 | mode=2 source=process |
| 线程回退 -> source=thread_fallback | 通过 | mode=1 source=thread_fallback |
| 进程与线程均失败 -> UNKNOWN | 通过 | mode=-1 source=unknown |
| 真实环境来源标记与诊断一致 | 通过 | src=process note=PER_MONITOR_DPI_AWARE（进程级查询确认） |
| query_dpi_awareness_detailed 返回合法来源 | 通过 | mode=2 source=process |

所有失败分支均使用 Mock，没有点击桌面图标。
