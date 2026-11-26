# Phase 1.1 Review Fix：DPI ctypes 声明与状态测试报告

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| GetThreadDpiAwarenessContext 返回 HANDLE(c_void_p) | 通过 | restype=<class 'ctypes.c_void_p'> argtypes=[] |
| GetAwarenessFromDpiAwarenessContext 参数 HANDLE + c_int 返回 | 通过 | argtypes=[<class 'ctypes.c_void_p'>] restype=<class 'ctypes.c_long'> |
| GetProcessDpiAwareness 参数/返回类型 | 通过 | argtypes=[<class 'ctypes.c_void_p'>, <class 'ctypes.wintypes.LP_c_long'>] restype=<class 'ctypes.HRESULT'> |
| SetProcessDpiAwareness 参数/返回类型 | 通过 | argtypes=[<class 'ctypes.c_long'>] restype=<class 'ctypes.HRESULT'> |
| SetProcessDPIAware 返回 BOOL | 通过 | restype=<class 'ctypes.c_long'> |
| 设置成功 + 查询成功 PM -> PM | 通过 | mode=2 |
| PM 设置失败 + 系统设置成功 + 查询 SYSTEM -> SYSTEM | 通过 | mode=1 |
| 设置失败 + 查询 UNAWARE -> UNAWARE | 通过 | mode=0 |
| 查询失败 -> UNKNOWN（不冒充 PM） | 通过 | mode=-1 label=DPI_AWARENESS_UNKNOWN（查询失败或未确认，状态未知） |
| 查询抛异常 -> UNKNOWN | 通过 | mode=-1 |
| 实际状态与报告一致 | 通过 | note=PER_MONITOR_DPI_AWARE（进程级查询确认） value=2 label=PER_MONITOR_DPI_AWARE |

未引入 PER_MONITOR_AWARE_V2；保留现有 PM v1 方案。
