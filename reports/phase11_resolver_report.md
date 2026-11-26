# Phase 1.1：窗口解析安全测试报告（Mock 窗口树）

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 命中 Progman 时拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链包含系统桌面窗口类 ['Progman', 'WorkerW']，拒绝发送 |
| 命中 WorkerW 时拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链包含系统桌面窗口类 ['Progman', 'WorkerW']，拒绝发送 |
| 命中 SHELLDLL_DefView 时拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链包含 SHELLDLL_DefView（桌面视图），拒绝发送 |
| 桌面 SysListView32 子窗口拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链包含系统桌面窗口类 ['Progman', 'WorkerW']，拒绝发送 chain=['SysListView32', 'SHELLDLL_DefView', 'Progman'] |
| WorkerW 下的桌面图标列表拒绝 | 通过 | reason=WindowFromPoint 命中: 父窗口链包含系统桌面窗口类 ['Progman', 'WorkerW']，拒绝发送 |
| 普通应用 SysListView32 不拒绝 | 通过 | class=SysListView32 reason=None |
| 父链查询异常时安全失败 | 通过 | reason=WindowFromPoint 命中: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 |
| 父链成环时安全失败 | 通过 | reason=WindowFromPoint 命中: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 |
| 父链超深时安全失败 | 通过 | reason=WindowFromPoint 命中: 父窗口链不可靠（异常/成环/超深/句柄失效），按安全失败策略拒绝发送 |
| 坐标转换失败时拒绝 | 通过 | reason=root 窗口客户区坐标转换失败，无法安全定位子窗口，拒绝按根窗口目标继续发送 |
| 命中自身 Overlay 拒绝 | 通过 | reason=命中 VirtualMouse 自身 Overlay（穿透失效？），拒绝发送 |

全部用例使用模拟窗口树，没有点击桌面图标，也没有调用任何输入 API。
