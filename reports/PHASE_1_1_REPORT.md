# VirtualMouse Phase 1.1 — 基础安全性与输入可靠性修复报告

执行日期：2026-11-26
仓库：`LemonsNight/uma-auto-test`（VirtualMouse/）
范围：只修复安全性、窗口解析准确性、输入消息完整性；未重写架构，未接入赛马娘。

---

## 1. 修改文件清单

| 文件 | 修改原因 |
|---|---|
| `core/window_resolver.py` | 加入可注入 `WindowApi`、父窗口链安全判定、桌面图标列表拦截、坐标转换失败拒绝 |
| `core/input_backend.py` | 加入 `ClickStatus` 分阶段状态、HWND 有效性检查、DOWN/UP 完整性、释放补救与注入式 Mock 接口 |
| `core/virtual_cursor.py` | 拒绝目标时设置 `ClickStatus.REJECTED_TARGET`，停止使用临时导入 |
| `core/coordinate.py` | DPI 感知设置后查询系统实际状态，避免误报 PM aware；不引入 PMv2 |
| `ui/main_window.py` | 结果面板显示状态、按键释放不确定性 |
| `tests/test_window_resolver_safety.py` | 新增：11 个模拟窗口树安全用例 |
| `tests/test_click_state.py` | 新增：12 个 Mock PostMessage 状态用例 |
| `tests/test_coordinate_boundaries.py` | 新增：5 个 LPARAM/DPI 边界用例 |
| `tests/test_desktop_smoke.py` | 新增：真实桌面只解析+移动圆点，不点击 |
| `tests/test_overlay_runtime.py` | 加入对照组，区分外部鼠标活动 |
| `tests/test_notepad_runtime.py` | 加入对照组，区分外部鼠标活动 |
| `README.md` / `reports/TEST_REPORT.md` / `reports/KNOWN_LIMITATIONS.md` | 同步 Phase 1.1 说明 |

---

## 2. 问题与修复

### 问题 1：桌面图标列表 `SysListView32` 会被误判为普通应用窗口

**原始表现**：Phase 1 只按最初命中 HWND 的类名判断，`_DESKTOP_CLASSES` 只含
`Progman` / `WorkerW` / `SHELLDLL_DefView`。本机真实桌面树为
`Progman → SHELLDLL_DefView → SysListView32("FolderView")`，
命中图标列表时类名是 `SysListView32`，不在拒绝名单中，点击消息会被发往桌面图标列表。

**修复**：
- 新增 `WindowApi` 只读查询包装，沿 `GetParent` 走完整父窗口链；
- 链上出现 `Progman` / `WorkerW` / `SHELLDLL_DefView` 或标题 `Program Manager` 即拒绝；
- `SysListView32` 只有在祖先链确认属于桌面结构时才拒绝，普通应用的同名类不拒绝；
- 在 WindowFromPoint 命中、候选子窗口、最终目标三个位置都做链检查，不能通过换目标绕过；
- 父链查询异常、成环、超过 32 层或句柄失效时按安全失败策略拒绝。

**验证证据**：
- Mock 用例 11/11 通过，含 4 个桌面拒绝、普通应用 `SysListView32` 放行、异常/成环/超深安全失败。
- 真实桌面冒烟：`坐标=(30,-57)` 命中 `SysListView32("FolderView")`，
  链 `['SysListView32','SHELLDLL_DefView','Progman']`，
  拒绝原因 `父窗口链包含系统桌面窗口类 ['Progman','WorkerW'], 拒绝发送`。
- 测试中未点击任何桌面图标。

### 问题 2：点击消息缺少分阶段状态，DOWN/UP 完整性无保障

**原始表现**：Phase 1 按固定顺序发三条消息，任一失败即 `break`。
虽然 DOWN 失败不会继续 UP，但结果对象只有 `all_messages_queued`，
无法区分失败发生在哪条消息；DOWN 成功而 UP 失败时既不记录按键可能未释放，
也不尝试补救，且可能被误读为"部分成功"。

**修复**：
- 新增 `ClickStatus`：`REJECTED_TARGET` / `TARGET_INVALID` / `LPARAM_OUT_OF_RANGE` /
  `MOUSEMOVE_FAILED` / `DOWN_FAILED` / `UP_FAILED` / `COMPLETE_QUEUED`；
- 每条消息单独记录 `MessageResult.attempt`（primary / release_recovery）；
- 发送前、DOWN 前、UP 前分别记录 `HwndCheck`；
- DOWN 失败不发送正常 UP；
- DOWN 成功但 UP 失败：`button_release_uncertain=True`，
  仅对**原 HWND**补发一次 `WM_LBUTTONUP`，记录 `release_recovery` 结果；
  若原 HWND 已失效则明确报告"无法保证释放"，不补发给任何其它窗口；
- `all_messages_queued` 仅在状态为 `COMPLETE_QUEUED` 且三条主消息全部入队时为真；
- `verification` 始终保持"未验证"，不把入队成功说成目标已处理点击。

**验证证据**：Mock 测试 12/12 通过，覆盖三消息全成功、MOUSEMOVE 失败、
DOWN 失败、UP 失败并补救、DOWN 后 HWND 销毁、发送前 HWND 失效、
目标被拒绝、LPARAM 越界、补救仍失败。所有失败分支均未报告完整成功。

### 问题 3：坐标转换失败静默沿用屏幕坐标

**原始表现**：`ScreenToClient` 抛异常时，代码记录 note 后
`client_x, client_y = coord.x, coord.y` 继续发送，可能点击到错误位置。

**修复**：转换失败写入 `reject_reason`，`is_safe_target=False`，后端不会发送任何消息。

**验证证据**：Mock 用例"坐标转换失败时拒绝"通过。

### 问题 4：DPI Awareness 状态可能误报

**原始表现**：设置调用失败后直接标为 UNAWARE；若系统其实已设置为其它级别，
报告可能与实际不符。

**修复**：设置后通过 `GetAwarenessFromDpiAwarenessContext` /
`GetProcessDpiAwareness` 查询系统实际状态并按实际报告；查询不到时不冒充 PM aware。
**未替换**为 `PER_MONITOR_AWARE_V2`。

**验证证据**：坐标测试 5/5 通过，含 -32768 / -32767 / 32767 / 越界 / 双屏负 Y。

---

## 3. 新增测试用例与执行结果

| 测试套件 | 用例数 | 通过 | 失败 |
|---|---:|---:|---:|
| `tests/test_window_resolver_safety.py` | 11 | 11 | 0 |
| `tests/test_click_state.py` | 12 | 12 | 0 |
| `tests/test_coordinate_boundaries.py` | 5 | 5 | 0 |
| `tests/test_desktop_smoke.py` | 6 | 6 | 0 |
| `tests/test_overlay_runtime.py`（原有） | 15 | 15 | 0 |
| `tests/test_input_module.py`（原有） | 15 | 15 | 0 |
| `tests/test_notepad_runtime.py`（原有） | 11 项记录 | 11 | 0 |
| `tests/test_mouse_isolation.py`（原有） | 2 组 | 2 | 0 |
| `tests/smoke_test_main.py`（原有） | 6 | 6 | 0 |

补充：`tools/env_check.py` 正常执行；记事本前台 / 部分遮挡 / 浏览器前台三个场景
均"入队成功 + 插入符变化"，即目标程序真实响应。

---

## 4. 输入安全性

- **是否调用过 `SetCursorPos`**：否。源码静态检查无命中。
- **是否调用过 `SendInput`**：否。源码静态检查无命中。
- **是否调用过 `mouse_event`**：否。源码静态检查无命中。
- **是否使用 `pyautogui`**：否。
- **是否使用 PostMessage**：是，且是唯一输入路径（
  `WM_MOUSEMOVE` → `WM_LBUTTONDOWN` → `WM_LBUTTONUP`），Phase 1 路径未改变。
- **是否发生真实鼠标位置变化**：程序未移动真实鼠标。
  隔离测试连续 5 次干净运行：对照组与 25 次"移动圆点 + 点击"实验组光标均保持不变。
  共享桌面偶发外部鼠标活动（有时对照组自身变化 1~70px），
  已在测试中加入对照组区分，不归因于本程序。
- **是否存在未释放按键状态**：正常路径无。
  Mock 测试验证了 DOWN 成功/UP 失败时会保留 `button_release_uncertain=True`
  并记录补救结果；真实环境未构造该失败场景（标记为**未验证**）。

---

## 5. 未解决问题 / 安全限制

1. **UP 补发仅代表入队**：补救 `WM_LBUTTONUP` 返回成功不等于目标已释放按键；
   结果对象始终保留不确定标志。真实触发场景（UP 入队失败）未实测，只有 Mock 覆盖。
2. **完全遮挡的目标无法点击**：坐标式设计只能命中当前位于该坐标的窗口。
3. **最小化窗口不可作为坐标目标**：原坐标解析到其它窗口或桌面并被拒绝。
4. **UIPI / 权限差异未实测**：代码记录 `GetLastError` 与限制说明，不绕过。
5. **不同 Qt / Windows 版本未验证**：只在 PySide6 6.12 + Windows 11 build 26200 实测。
6. **PMv2 未采用**：仅说明兼容性影响后保留现有 PM v1 方案。
7. **共享桌面外部鼠标活动**：测试偶发 1~2px 光标漂移，已用对照组区分。

---

## 6. 下一阶段建议（不自动开始）

- 若需要更复杂的后台点击，可评估 UI Automation 的可达性，但需单独评估兼容性与权限。
- 如需覆盖 UP 入队失败的真实场景，可设计一个专门的可控测试窗口制造消息入队失败。
- 不建议进入赛马娘业务自动化前跳过对受保护窗口/权限场景的验证。

---

## 7. 结论

Phase 1.1 的 9 项完成标准全部满足：桌面及图标列表不再被误判、
普通应用 `SysListView32` 不被全局拒绝、点击各阶段状态明确、
DOWN/UP 失败处理安全、HWND 失效停止、坐标边界通过、
原有与新增测试全部通过、真实鼠标位置未被程序改变、未引入驱动或新输入方案、文档完整更新。

等待主 Agent 审查。
