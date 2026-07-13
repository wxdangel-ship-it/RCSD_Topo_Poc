# T11 性能研究记录

## 已确认事实

- 工作树：`E:\Work\RCSD_Topo_Poc__wt_t11_performance_20260713`
- 分支：`codex/t11-performance-60pct-20260713`
- 优化前提交：`31fa58fe751eb0724feab86ad8dcadd48a5cea8b`
- 正式提取入口：`scripts/t11_extract_relation_repair_candidates.py`
- 冻结 T10 输入：`outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full/cases/<case_id>`
- Python 环境：主仓库 `.venv`，工作树代码通过 `PYTHONPATH=<worktree>/src` 加载。

## 已采集

- Python `3.10.12`、GeoPandas `1.1.3`、Shapely `2.1.2`、pandas `2.3.3`；运行环境不提供 `osgeo` Python 模块，实际矢量 IO 沿用 GeoPandas/pyogrio。
- 六用例优化前逐用例墙钟、内部耗时、峰值内存及候选数。
- `1885118` profile 累计耗时 Top 项，热点为重复 50m RCSD 距离计算和独立进程重复导入。
- 优化前与正式批量输出的 semantic tree manifest；六例各 14 个结构化产物完全等价。
- 正式批量 `workers=2` 总墙钟 `26.85s`、峰值 RSS `255796 KiB`、退出状态 `0`。

完整结论见 `analyze.md`。

## 判定边界

- T11 性能口径只覆盖正式 T11 候选关系提取入口。
- 串联 T05/T06 的人工比较脚本只做兼容性回归，不把上游模块耗时计入 T11 性能目标。
- 任何候选数量、业务字段、几何、CRS、排序或文件缺失均判定为不等价。
