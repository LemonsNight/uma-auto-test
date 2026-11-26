# Phase 1.1 Review Fix：父窗口链异常安全测试报告

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 命中窗口 GetClassName 异常 -> 拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 reliable=False |
| 中间父窗口 GetClassName 异常 -> 拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 reliable=False |
| GetWindowText 异常但类名正常 -> 不因标题拒绝 | 通过 | reason=None title_flags=[True] |
| 桌面父窗口链仍然拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链包含系统桌面窗口类 ['Progman', 'WorkerW']，拒绝发送 chain=['SysListView32', 'SHELLDLL_DefView', 'Progman'] |
| 普通应用 SysListView32 仍然允许 | 通过 | reason=None chain=['SysListView32', 'MyApp'] |
| GetParent 异常 -> 安全失败 | 通过 | reason=WindowFromPoint 命中: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 |
| IsWindow 异常 -> 安全失败 | 通过 | reason=WindowFromPoint / IsWindow 查询异常，安全失败: 模拟 IsWindow 异常 |

全部使用模拟窗口树，未点击任何真实窗口。
