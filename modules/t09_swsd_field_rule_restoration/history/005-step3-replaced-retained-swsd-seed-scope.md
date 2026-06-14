# 005 Step3 replaced+retained_swsd carrier seed scope

- 时间：2026-06-13
- 模块：T09 SWSD Field Rule Restoration / Step3 F-RCSD restriction
- 变更类型：F-RCSD Arm carrier 选择收敛

## 根因

T10 991176 在 T06 Step3 增加 `replaced+retained_swsd` relation 后，T09 Step3 的 `from_arm_approach_missing / to_arm_exit_missing` 回归被修复，但 restriction 明细出现过产出风险：同一个 Segment relation 中保留了多个 detached junc 的 `source=2` SWSDRoad，T09 只按端点是否命中 junction alias 选择 carrier，没有继续校验该 `source=2` Road 是否属于当前 Arm 的 `approach_road_ids / exit_road_ids`。

典型现象是 `1049584`：`arm:74641222` 与 `arm:1029919` 同属 `replaced+retained_swsd` Segment relation，T09 把 `1029919` 混入 `arm:74641222` 的 exit carrier，形成额外 link-pair restriction。

## 业务逻辑变更

沿用既有 `retained_swsd` 规则，把 seed scope 扩展到 `replaced+retained_swsd`：

1. `relation_status in {"retained_swsd", "replaced+retained_swsd"}` 且 `source=2` 的 relation road，只有 road id 属于当前 Arm 的 `approach_road_ids` 时，才可作为 approach carrier。
2. 同类 `source=2` relation road 只有 road id 属于当前 Arm 的 `exit_road_ids` 时，才可作为 exit carrier。
3. `source=1` 的 RCSD carrier 不套用 SWSD seed id 约束，仍按 T06 relation node map 与 F-RCSD road direction 判断。
4. 未进入 relation 的 retained SWSD seed fallback 规则不变。

## 安全边界

- 不改变 T06 relation 输出，不回写 T06/T05。
- 不改变 restored SWSD movement 结论；只影响 F-RCSD link-pair 投影时的 carrier 选择。
- `replaced+retained_swsd` 中的 `source=2` Road 仍只表达 detached junc 局部 carrier，不表达 RCSD 锚定成功。

## GIS / 拓扑检查

- CRS 与坐标变换：不新增几何计算，继续读取 T06 F-RCSD 与 T09 JSON/CSV 归一化输出。
- 拓扑一致性：不 silent fix；通过 Arm seed membership 限制 source=2 carrier，避免同 Segment 其它 Arm 的 SWSDRoad 被交叉组合。
- 几何语义可解释性：source=2 carrier 使用原 SWSD Road id 与方向，source=1 carrier 仍由 T06 relation 与 F-RCSD direction 解释。
- 审计可追溯性：输出保留 arm relation status、road source、risk flags 与 skip reason；履历记录状态扩展。
- 性能可验证性：仅增加集合成员判断，不增加图搜索。

## 回归

- 扩展 `test_step3_retained_swsd_relation_keeps_carrier_within_arm_seed_roads`：
  - `retained_swsd` 保持既有 seed scope 行为。
  - `replaced+retained_swsd` 的 `source=2` relation road 同样必须落在当前 Arm seed 内，不能把同 Segment 其它 Arm 的 SWSDRoad 混入 restriction link pair。
