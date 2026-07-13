# T11 六用例性能分析与验收

## 1. 固定环境

- 优化前代码提交：`31fa58fe751eb0724feab86ad8dcadd48a5cea8b`
- 临时工作树：`E:\Work\RCSD_Topo_Poc__wt_t11_performance_20260713`
- Python：`3.10.12`
- GeoPandas：`1.1.3`
- Shapely：`2.1.2`
- pandas：`2.3.3`
- 冻结输入：`outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full/cases/<case_id>`

## 2. 优化前六用例基线

六个 Case 分别通过原单用例 CLI 独立执行，墙钟总耗时为 `58.40s`，目标线为 `35.04s`。

| Case | 墙钟耗时 | 总耗时占比 | 峰值 RSS KiB | 候选数 |
| --- | ---: | ---: | ---: | ---: |
| `1885118` | 15.61s | 26.73% | 198464 | 623 |
| `605415675` | 9.07s | 15.53% | 148072 | 173 |
| `609214532` | 13.03s | 22.31% | 180196 | 470 |
| `706247` | 6.87s | 11.76% | 145208 | 262 |
| `74155468` | 6.64s | 11.37% | 123504 | 46 |
| `991176` | 7.18s | 12.29% | 125648 | 57 |

六例 summary 内部处理时间合计 `33.272133s`，独立进程启动、依赖加载及入口固定开销约 `25.13s`，占总墙钟约 `43.0%`。

## 3. profile 结论

`1885118` 优化前 cProfile 显示：

- `extract_t11_relation_repair_candidates` 累计 `15.059s`。
- `build_segment_relation_review_tables` 累计 `8.242s`。
- `_rcsd_50m_context` 调用 `2528` 次，累计 `6.867s`。
- 每次独立进程的 Python/GeoPandas 导入累计约 `4.43s`。

热点由两部分组成：重复节点 50m RCSD 全层距离计算，以及六次独立进程重复加载相同依赖。

## 4. 实施优化

1. `_rcsd_50m_context` 按 `target_id` 缓存，避免同一节点因关联多个 Segment 重复计算。
2. 50m 查询先用 GeoPandas spatial index 裁剪包络候选，再执行原始精确 `distance <= 50.0` 判定；无 50m 命中时通过 spatial index nearest 取得精确最近距离。
3. 既有 T11 正式入口增加向后兼容的批量模式；六例在一次依赖加载后以 `workers=2` 并行执行，每个 Case 使用独立输出根。
4. 单用例模式、业务 callable、候选规则、CRS、几何、排序、字段和输出文件集合均未改变。

## 5. 正式性能验收

正式批量命令：

```bash
PYTHONPATH=<worktree>/src /usr/bin/time -v \
  <python> scripts/t11_extract_relation_repair_candidates.py \
  --t10-suite-root <frozen_cases_root> \
  --out-root <formal_batch_output> \
  --workers 2
```

| 指标 | 优化前 | 优化后 | 结论 |
| --- | ---: | ---: | --- |
| 六用例总墙钟 | 58.40s | 26.85s | 下降 54.02% |
| 耗时比 | 100% | 45.98% | 低于 60% 目标 |
| 等效吞吐 | 1.000x | 2.175x | 提升约 117.5% |
| 峰值 RSS | 198464 KiB（独立进程最大值） | 255796 KiB | 并行换取吞吐，增加约 28.9% |
| 退出状态 | 6/6 为 0 | 批量入口为 0 | 通过 |

原始证据：

- 优化前：`outputs/_work/t11_performance_20260713/reference/<case_id>/time.txt`
- 优化后：`outputs/_work/t11_performance_20260713/formal_batch_w2/time.txt`
- 优化后 stdout：`outputs/_work/t11_performance_20260713/formal_batch_w2/stdout.json`
- 六例业务等价审计：`outputs/_work/t11_performance_20260713/formal_batch_w2/equivalence.json`

## 6. 业务等价与 GIS/QA

- `1885118` 先行门禁：候选数仍为 `623`，14 个 CSV/JSON/GPKG 结构化产物等价。
- 六用例正式批量回归：每例 14 个 CSV/JSON/GPKG 结构化产物均通过 semantic manifest 比较；无缺失、无新增、无内容变化。
- 每例另有 4 个 XLSX。优化前后只存在 `docProps/core.xml` 中 `dcterms:created / dcterms:modified` 运行时间差异；规范化这两个非业务时间字段后，工作表 XML、共享字符串、样式、下拉验证及其余 ZIP 条目逐字节一致。
- CRS：保持原输入/输出 CRS，未增加坐标转换。
- 拓扑：T11 仍为只读审计，不执行 snap、dissolve、repair 或 silent fix。
- 几何：候选点和 Segment 几何未改变；空间索引只缩小待精确计算的候选集合。
- 审计：输入 root、Case 顺序、worker 数、输出 root、逐 Case summary、总墙钟和峰值 RSS 均可定位。

## 7. 测试与体量

- `tests/modules/t11_manual_relation_review`：`30 passed`。
- Python compileall：通过。
- `git diff --check`：通过。
- T11 模块、相关脚本、测试和 QGIS 插件共 24 个源码/脚本文件全部低于 `61440` 字节；最大文件为 `extract.py`，工作树大小 `56222` 字节。
