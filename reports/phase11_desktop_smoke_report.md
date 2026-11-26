# Phase 1.1：真实桌面冒烟测试报告（无点击）

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 找到 Progman 桌面窗口 | 通过 | HWND=['0x20cca'] |
| 找到 SHELLDLL_DefView | 通过 | ['0x20cbc'] |
| 找到桌面 SysListView32(FolderView) | 通过 | ['0x20cbe'] |
| 真实桌面图标区域解析被拒绝 | 通过 | 坐标=(30, -57) hit=HWND=0x20CBE class='SysListView32' title='FolderView' client=(30, -57) reason=WindowFromPoint 命中: 父窗口链包含系统桌面窗口类 ['Progman', 'WorkerW']，拒绝发送 chain=['SysListView32', 'SHELLDLL_DefView', 'Progman'] |
| 圆点可移动到桌面图标坐标（不点击） | 通过 | 坐标=(30, -57) 圆点中心=(30, -57) |
| 真实鼠标位置（仅记录） | 通过 | (2353, 565) |

本测试没有调用任何 PostMessage / SendInput / 鼠标点击 API；只读取窗口树并移动圆点。
