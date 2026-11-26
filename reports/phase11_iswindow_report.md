# Phase 1.1 Final Review — IsWindow 异常安全补丁测试报告

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 正常窗口放行并统计 IsWindow 调用 | 通过 | reject=None total_iswindow_calls=7 |
| IsWindow(ancestor) 抛异常 -> 明确拒绝 | 通过 | reason=IsWindow(ancestor) 查询异常，安全失败: 模拟第 2 次 IsWindow 异常 reliable=False root=0x0 nth=2 |
| IsWindow(ancestor) 异常 -> 后端 PostMessage 调用数为 0 | 通过 | post_calls=0 status=rejected_target |
| 最终目标 IsWindow 异常 -> 明确拒绝 | 通过 | reason=最终目标 IsWindow 查询异常，安全失败: 模拟第 6 次 IsWindow 异常 nth=6 |
| 最终目标 IsWindow 异常 -> 后端 PostMessage 调用数为 0 | 通过 | post_calls=0 status=rejected_target |
| 最终目标 IsWindowEnabled 异常不泄漏 | 通过 | 未泄漏 |
| 最终目标 IsWindowEnabled 异常 -> 明确拒绝 | 通过 | reason=最终目标 IsWindowEnabled 查询异常，安全失败: 模拟第 1 次 IsWindowEnabled 异常 enabled_calls=1 |
| 最终目标 IsWindowEnabled 异常 -> 后端 PostMessage 调用数为 0 | 通过 | post_calls=0 status=rejected_target |
| 普通应用正常子窗口仍然放行 | 通过 | target=0xB reason=None |

Mock 使用调用计数精确控制第 N 次 IsWindow / IsWindowEnabled 抛异常，
避免只覆盖 _walk_chain 的前置检查。所有拒绝场景均通过
PostMessageBackend 注入 post_fn 验证调用数为 0。
