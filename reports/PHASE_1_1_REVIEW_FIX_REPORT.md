# VirtualMouse Phase 1.1 Review Fix — 主 Agent 审查问题修复报告

执行日期：2026-11-26
基线：`main` 分支 `7e8136a`
范围：小范围审查修复，不重构架构，不开始 Phase 2，不修改 PostMessage 输入方案。

---

## 一、任务 1：父窗口链类名读取失败安全策略

### 原问题

`_walk_chain()` 使用 `_safe_class_name()` / `_safe_window_text()`，两者吞掉异常返回空字符串。
当 `GetClassName` 失败时，空类名会被当作"已知且非桌面"继续放行，
可能遗漏系统桌面祖先，导致向桌面图标区域发送点击。

### 修改方案

- `_walk_chain()` 直接调用 `api.get_class_name(current)`，失败或返回空字符串时立即返回
  `(chain, False)`，链不可靠；
- `IsWindow`、`GetParent` 查询抛异常也分别捕获并标记不可靠；
- 成环、超过 32 层、句柄失效保持原有的不可靠判定；
- `GetWindowText` 失败只写入 `ChainNode.title_read_failed=True` 作为诊断信息，
  不替代类名安全检查；
- `resolve()` 入口处的 `WindowFromPoint` / `IsWindow` 查询同样加异常保护（审查中发现的连带缺陷）。

### Mock 测试证据

`tests/test_window_chain_errors.py`：7/7 通过。

| 用例 | 结果 |
|---|---|
| 命中窗口 GetClassName 异常 -> 拒绝 | 通过 |
| 中间父窗口 GetClassName 异常 -> 拒绝 | 通过 |
| GetWindowText 异常但类名正常 -> 仅诊断、不拒绝 | 通过 |
| 正常桌面父窗口链（Progman→SHELLDLL_DefView→SysListView32）仍拒绝 | 通过 |
| 普通应用 SysListView32 仍允许 | 通过 |
| GetParent 异常 -> 安全失败 | 通过 |
| IsWindow 异常 -> 安全失败 | 通过 |

### 真实 Windows 验证证据

`tests/test_desktop_smoke.py`：6/6 通过。真实桌面链
`SysListView32("FolderView") → SHELLDLL_DefView → Progman` 被拒绝，
拒绝原因来自父窗口链中的 `Progman` / `WorkerW`。
`tests/test_notepad_runtime.py`：记事本前台/遮挡/浏览器前台三场景均通过，
说明普通应用的链检查未误伤。

---

## 二、任务 2：RealChildWindowFromPoint 坐标系

### 原问题

`resolve()` 把桌面坐标 `coord.x/coord.y` 直接传给 `RealChildWindowFromPoint`。
该 API 要求**目标窗口的客户区坐标**，屏幕坐标在窗口原点非零时会指向错误位置，
可能定位到错误子窗口或错误目标。

### 修改方案

- 调用前先 `screen_to_client(root_hwnd, coord.x, coord.y)` 得到客户区坐标；
- `real_child_window_from_point(root_hwnd, root_client_x, root_client_y)` 使用客户区坐标；
- 子窗口 `GetWindowRect` 校验继续使用屏幕坐标；
- 转换失败时不调用 `RealChildWindowFromPoint`，并给结果明确 `reject_reason`，
  不静默回退到根窗口目标。

### Mock 测试证据

`tests/test_real_child_coordinates.py`：6/6 通过。
root 屏幕原点 `(300, 200)`，桌面坐标 `(350, 260)` -> 客户区 `(50, 60)`；
断言 `RealChildWindowFromPoint` 收到 `(1, 50, 60)`，
并断言子窗口 `GetWindowRect` 仍被查询（屏幕坐标校验）。
转换失败时 API 调用次数为 0，结果被拒绝。

### 真实 Windows 验证证据（严格区分）

1. **真实验证的是 `WindowFromPoint` 子窗口命中与坐标转换结果**：
   `tests/test_notepad_runtime.py` 三场景（前台 / 部分遮挡 / 浏览器前台）通过。
   解析器命中的是现代记事本文本区子窗口 `RichEditD2DPT`（见日志中的
   `class='RichEditD2DPT'`），`ScreenToClient` 得到的客户区坐标与插入符变化
   共同说明：真实环境下"桌面坐标 -> 目标子窗口 -> 客户区坐标"这条链路是正确的。

2. **未在真实环境逐字节验证的是 `RealChildWindowFromPoint` 的 API 入参**：
   现代记事本场景中 `WindowFromPoint` 直接命中子窗口，代码走的是
   `is_child=True` 分支，**没有调用** `RealChildWindowFromPoint`。
   因此"API 收到客户区坐标 `(50,60)` 而非屏幕坐标 `(350,260)`"这一结论
   只由 `tests/test_real_child_coordinates.py` 的 Mock 断言证明，
   **不能在真实环境证据中声称已验证**。

3. `tests/test_desktop_smoke.py` 只验证真实桌面窗口树的解析拒绝与圆点移动，
   未点击桌面图标，也未验证 `RealChildWindowFromPoint` 入参。

结论：`RealChildWindowFromPoint` 坐标修正 = **Mock 已验证 / 真实 API 入参未验证**；
`WindowFromPoint` 子窗口命中、客户区坐标转换、记事本插入符变化 = **真实环境已验证**。

---

## 三、任务 3：DPI API ctypes 声明与未知状态

### 原问题

DPI 相关 API 缺少完整 `argtypes` / `restype`。64 位下 DPI_AWARENESS_CONTEXT 是句柄，
若按 32 位整数处理会截断。查询失败时的状态也需要明确标记为未知。

### 修改方案

- `GetThreadDpiAwarenessContext`：`argtypes=[]`，`restype=wintypes.HANDLE`（c_void_p）；
- `GetAwarenessFromDpiAwarenessContext`：`argtypes=[HANDLE]`，`restype=c_int`；
- `GetProcessDpiAwareness`：`argtypes=[HANDLE, POINTER(c_int)]`，`restype=HRESULT`；
- `SetProcessDpiAwareness`：`argtypes=[c_int]`，`restype=HRESULT`；
- `SetProcessDPIAware`：`argtypes=[]`，`restype=BOOL`；
- 保留 `PER_MONITOR_DPI_AWARE`（v1），**不引入 PMv2**；
- 新增 `DpiAwareness.UNKNOWN=-1`；设置+查询逻辑抽成可注入的 `_apply_dpi_awareness()`，
  查询失败或抛异常一律返回 UNKNOWN，并输出 `DPI_AWARENESS_UNKNOWN` 标签，
  不冒充 PM aware。

### Mock 测试证据

`tests/test_dpi_declarations.py`：11/11 通过。
覆盖 API 声明类型检查、设置成功/失败、查询成功/失败/抛异常、
UNKNOWN 不冒充 PM，以及真实进程状态与报告一致。

### 真实 Windows 验证证据

`tools/env_check.py` 正常执行；本机 PySide6 6.12 + Windows 11 build 26200：
`enable_per_monitor_dpi_awareness()` 返回 `PER_MONITOR_DPI_AWARE`，
`current_dpi_mode_value()` 为 2，查询声明 `restype=c_void_p`，未发生句柄截断。

---

## 四、完整回归结果

| 测试套件 | 用例数 | 通过 | 失败 |
|---|---:|---:|---:|
| `tools/env_check.py` | 环境诊断 | OK | 0 |
| `tests/test_overlay_runtime.py` | 15 | 15 | 0 |
| `tests/test_input_module.py` | 15 | 15 | 0 |
| `tests/test_window_resolver_safety.py` | 11 | 11 | 0 |
| `tests/test_click_state.py` | 12 | 12 | 0 |
| `tests/test_coordinate_boundaries.py` | 5 | 5 | 0 |
| `tests/test_desktop_smoke.py` | 6 | 6 | 0 |
| `tests/test_window_chain_errors.py` | 7 | 7 | 0 |
| `tests/test_real_child_coordinates.py` | 6 | 6 | 0 |
| `tests/test_dpi_declarations.py` | 11 | 11 | 0 |
| `tests/test_mouse_isolation.py` | 2 组采样 | 2 | 0 |
| `tests/smoke_test_main.py` | 6 | 6 | 0 |
| `tests/test_notepad_runtime.py` | 11 项记录 | 11 | 0 |

真实桌面冒烟只做窗口解析和圆点移动，**未点击任何桌面图标**。

---

## 五、尚未验证的情况

1. **真实 Windows 下 GetClassName / GetParent / IsWindow 异常分支**：
   仅通过 Mock 模拟；实际系统极少返回这些异常，无法稳定复现。
2. **真实 root 窗口原点非零时的 RealChildWindowFromPoint 行为**：
   Mock 验证了坐标转换链路；真实记事本测试间接通过，但未逐字节断言 API 入参。
3. **DPI 查询失败的真实场景**：仅 Mock 模拟；本机查询始终成功。
4. **UIPI / 受保护窗口、其它 Qt/Windows 版本**：仍未验证。
5. **共享桌面外部鼠标活动**：多次出现对照组自身光标漂移（几十像素），
   程序行为以静默运行的隔离实验（对照组与实验组均不变）与静态检查为准。

---

## 六、结论

三项审查问题均已修复，新增 24 个 Mock/声明用例全部通过，原有测试全部回归通过。
未改变 PostMessage 输入方案，未引入 PMv2，未引入新依赖，未开始 Phase 2。

等待主 Agent 审查。

---

## 七、Phase 1.1 Final Review（最后一轮小范围修复）

### 任务 1：GetAncestor 异常安全处理

- **原问题**：`root_hwnd = self.api.get_ancestor(...) or hit_hwnd` 没有异常保护，
  异常时会把 hit_hwnd 当成未经确认的 root 继续使用。
- **修改**：`GetAncestor` 异常或返回无效 HWND 时，立即返回带明确 `reject_reason`、
  `chain_reliable=False`、`root_hwnd=0` 的 `ResolvedTarget`，不继续解析、不发送输入。
- **Mock 证据**：`tests/test_final_review_fixes.py` 18/18 通过，其中：
  GetAncestor 抛异常 -> 拒绝且 `chain_reliable=False`；`root_hwnd=0`；
  后端 `PostMessage` 调用次数为 0；返回无效 HWND 同样拒绝。

### 任务 2：候选子窗口安全失败禁止回退根窗口

- **原问题**：候选子窗口判定不安全时只写 notes，最终目标仍可能是 root_hwnd。
- **修改**：候选子窗口属于桌面结构、HWND 失效、`GetClassName`/`GetParent` 异常、
  `GetWindowRect` 异常、`RealChildWindowFromPoint` 查询异常时，
  设置最终 `reject_reason`，并把目标明确设为不安全候选 HWND，
  不再以 root_hwnd 作为可发送目标。
- **Mock 证据**：桌面结构候选子窗口、父链异常、HWND 失效、`GetClassName` 异常
  均返回拒绝，且注入的后端 `PostMessage` 调用次数为 0；
  普通应用正常子窗口仍放行（目标 HWND 正确、无拒绝原因）。

### 任务 3：DPI 查询顺序与诊断语义

- **原问题**：先查线程 DPI Context 再查进程级，且诊断中可能把线程结果说成进程确认。
- **修改**：新增 `query_dpi_awareness_detailed()`，优先 `GetProcessDpiAwareness`；
  失败后才用线程 `GetThreadDpiAwarenessContext` 回退，来源标记为
  `process` / `thread_fallback` / `unknown`；状态标签区分
  "进程级查询确认"与"仅线程级回退结果，非进程级确认"；完全失败仍为 UNKNOWN。
  设置策略与 PM v1 方案不变，未引入 PMv2。
- **Mock 证据**：进程级成功、线程回退、两者均失败三种分支均通过；
  真实环境状态标签与来源标记一致。

### 测试与回归

`tests/test_final_review_fixes.py`：18/18 通过。全部原有测试回归通过：
圆点 15/15、输入模块 15/15、解析器安全 11/11、点击状态 12/12、
坐标边界 5/5、桌面冒烟 6/6、窗口链异常 7/7、RealChild 坐标 6/6、
DPI 声明 11/11、记事本三场景通过、主程序冒烟 6/6。
真实桌面冒烟只解析与移动圆点，未点击桌面图标。

### 专项确认（本轮实跑）

| 确认项 | 证据 |
|---|---|
| 原有 PostMessage 路径未变化 | `git diff 08460e2 -- core/input_backend.py` 为空；静态检查无禁用 API |
| 桌面窗口仍然拒绝 | `phase11_desktop_smoke_report.md`：真实链 `SysListView32→SHELLDLL_DefView→Progman` 拒绝 |
| 普通应用 SysListView32 仍然允许 | `phase11_review_chain_report.md`：`reason=None chain=['SysListView32','MyApp']` |
| 普通应用正常子窗口仍然允许 | `phase11_final_review_report.md`：`target=0xB reject=None` |
| 不安全候选子窗口不回退根窗口 | 三类拒绝场景均 `post_calls=0`，目标保留为不安全候选 HWND |
| 真实鼠标位置未被程序改变 | 隔离测试静默时段对照组与实验组均不变；偶发外部漂移已用对照组区分 |

### 尚未验证

真实 Windows 下 GetAncestor / 候选子窗口查询异常分支无法稳定复现，仅 Mock 覆盖；
`RealChildWindowFromPoint` 真实 API 入参仍未逐字节断言；
UIPI / 其它 Qt/Windows 版本未验证；共享桌面偶发外部鼠标活动已用对照组区分。
