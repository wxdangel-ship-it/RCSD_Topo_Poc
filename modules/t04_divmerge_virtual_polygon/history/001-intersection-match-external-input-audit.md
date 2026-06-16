# 001 Intersection Match External Input Audit

## 时间

2026-06-15

## 背景

内网端到端执行中，T04 final closeout 读取可选的 T07 `intersection_match_t07.geojson` 时，遇到文件存在但内容为空或不是合法 JSON 的情况。旧逻辑直接 `json.loads()`，导致 `JSONDecodeError` 中断 T04 与后续链路。

T07/T03 intersection match 在 T04 中只用于跨模块 1:1 cardinality 校验，不改变 Step1-7 构面算法；因此可选外部输入不可消费时，应当进入审计并按 0 条外部成功关系继续，而不能阻断 T04 自身 relation 发布。

## 业务逻辑变更

- T04 `intersection_match.py` 对可选 T07/T03 intersection match 增加读取状态审计。
- 文件存在但为空、非法 JSON、或不是包含 `features` list 的 GeoJSON 时，不再抛出 `JSONDecodeError`；该输入按 0 条外部成功关系参与校验。
- `intersection_match_t04_summary.json` 新增 `t07_validation_input / t03_validation_input / external_validation_unusable_input_count`，记录外部输入是否可消费、不可消费原因与实际读取记录数。
- 路径不存在仍保持硬错误，避免把配置错误静默吞掉。
- 补充 `write_t04_nodes_outputs` 链路回归覆盖，确保 T04 nodes 发布阶段调用 `write_intersection_match_t04` 时也能把空 T07/T03 match 文件写入 summary 审计并继续发布 T04 自身关系。

## 边界

- 不改变 T04 Step1-7 构面算法。
- 不把不可消费的 T07/T03 输入解释为成功 relation。
- 不改变 cardinality 冲突压制和 T04 one-target-to-many rollback 规则。

## 验证

- `python -m py_compile src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/intersection_match.py`
- `python -m pytest tests/modules/t04_divmerge_virtual_polygon/test_intersection_match_t04.py -q`
