# T06 Step3 Segment Replacement and Junction Rebuild Plan

## Scope

本任务将 T06 正式范围扩展到 Step3：消费 Step2 replaceable RCSDSegment，输出融合后的 F-RCSD Road / Node，并重建受影响的语义路口 C。

本计划只覆盖 T06 Step3，不修改 T01 / T05 主链，不对 Step2 rejected Segment 做补救替换。

## Files

预计涉及：

- `modules/t06_segment_fusion_precheck/INTERFACE_CONTRACT.md`
- `modules/t06_segment_fusion_precheck/README.md`
- `modules/t06_segment_fusion_precheck/AGENTS.md`
- `modules/t06_segment_fusion_precheck/architecture/*.md`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/runner.py`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/schemas.py`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement.py`
- `tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py`
- Project source facts that currently describe T06 as Step1 / Step2 only.

是否调整 `scripts/t06_run_innernet_precheck.py` 需要单独确认；该脚本目前是 Step1 + Step2 包装，改变其官方调用行为会触发入口契约同步。

## Implementation Shape

1. 先更新 T06 source facts：T06 正式范围从 precheck 扩展为 Step1 / Step2 / Step3，但标注当前 Step3 implementation 状态。
2. 新增模块内 callable runner，不新增 repo CLI：
   - `run_t06_step3_segment_replacement(...)`
   - `run_t06_segment_fusion_precheck(...)` 是否默认串联 Step3 需在实现前确认。
3. 新增 Step3 纯函数与 orchestration：
   - parse replacement units。
   - compute removed SWSD road ids。
   - compute removed SWSD endpoint node ids。
   - compute retained RCSD road/node ids。
   - build junction C and C-to-segment relations。
   - rebuild C mainnodeid and inherited attributes。
   - write F-RCSD road/node and audit outputs。
4. 保持 Step1 / Step2 现有输出兼容。

## Outputs

Step3 输出目录建议：

```text
<out_root>/<run_id>/step3_segment_replacement/
```

建议输出：

- `t06_frcsd_road.gpkg/csv/json`
- `t06_frcsd_node.gpkg/csv/json`
- `t06_step3_replacement_units.gpkg/csv/json`
- `t06_step3_junction_rebuild_audit.gpkg/csv/json`
- `t06_step3_removed_swsd_roads.csv/json`
- `t06_step3_removed_swsd_nodes.csv/json`
- `t06_step3_added_rcsd_roads.csv/json`
- `t06_step3_added_rcsd_nodes.csv/json`
- `t06_step3_id_collision_audit.gpkg/csv/json`
- `t06_step3_summary.json`

F-RCSD 主输出文件名固定为 `t06_frcsd_road.* / t06_frcsd_node.*`。

## Parameters

第一版 Step3 不引入空间阈值参数，完全消费 Step2 retained 结果。

可配置项建议：

- 独立 Step3 runner 与 `scripts/t06_run_step3_segment_replacement.py`，避免改变现有 Step1 + Step2 内网脚本默认行为。
- `source_field_name="source"`。
- `rcsd_source_value=1`。
- `swsd_source_value=2`。
- `id_collision_policy="keep_original_ids_and_audit_with_source_field"`。

## Risks

- SWSD 与 RCSD id 空间可能冲突，影响 F-RCSD 单层输出主键稳定性。
- `mainnodeid` 对 main node 自身的取值口径需要与 T01/T04/T05 统一。
- Step2 retained node ids 若只覆盖 road endpoints，可能不足以表达 RCSD 语义路口组内所有需要写出的 node。
- 多个 replaceable Segment 汇入同一个 C 时，如果逐 Segment 重建而非按 C 聚合，容易重复覆盖属性或产生不一致 mainnodeid。
- 改变 `scripts/t06_run_innernet_precheck.py` 默认行为会影响既有内网验证脚本，需要单独登记入口行为变化。

## Verification

- Unit tests for Step3 pure functions.
- T06 pytest suite.
- `py_compile` on changed Python files.
- `git diff --check`.
- 对 XS1 切片执行 Step1 + Step2 + Step3，检查：
  - F-RCSD road/node 数量守恒关系。
  - removed / added / retained 数量可解释。
  - `source` 字段完整。
  - C 重建审计与输入 Segment 关系一致。
