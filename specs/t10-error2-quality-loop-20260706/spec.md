# T10-Error-2 20 Segment 未替换 RCSD 质量闭环规格

**状态**：SpecKit specify / plan / tasks 草案
**Scope Mode**：分阶段 implement
**Source Fact Status**：本文件是变更工件，不替代项目级或模块级 source-of-truth。正式业务口径若发生变化，必须同轮同步到对应模块源事实与契约。

## 1. 背景

本轮输入是 `E:\TestData\POC_Data\T10-Error-2` 中 20 个本地测试用例的主 Segment 未替换 RCSD 清单，以及 T11 内网人工标注路口锚定成果：

```text
/mnt/c/Users/admin/.codex/attachments/3ead6630-3147-40e4-838f-24e0a4adaa83/pasted-text.txt
/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t11_manual_export_archive/20260702T082301Z
```

目标不是只跑通一次 T05/T06，而是形成按根因迭代的闭环：每个根因修复必须先在 20 Segment 上回归，再跑 `1885118`，最后跑 T10 6 case，且业务效果不能回退。

## 2. 产品视角

质检人员需要知道每条未替换 RCSDRoad 在目标 Segment 下的归属和状态：

- 是否确实属于该主 Segment 的替换范畴。
- 是否已被当前或修复后 T06 Step3 消费。
- 若未被消费，是 T05 relation 缺口、T06 Step1 证据/锚点门禁、T06 Step2 relation/topology 硬审计、非目标 Segment 范围，还是当前 Step3 未复现。
- 哪些问题可以由既有 T11 人工 relation 或 T10 feedback 安全修复，哪些必须回到人工复核或源事实裁定。

## 3. 架构视角

本轮涉及 T05、T06、T10、T11 的边界：

- T11 Excel/CSV 是人工审计输入源；T05 只消费正向人工 relation，不消费空白、`NULL`、`no_valid_relation`、`uncertain`。
- T10 side-group / pair-anchor feedback 只能按 T05 契约补充 RCSDNode grouping，不能单独创建 SWSD-RCSD relation。
- T06 Step1 可以在源事实允许范围内消费 T05 发布的 `T11_MANUAL` relation，释放受控证据/锚点门禁。
- T06 Step2/Step3 仍是 replaceable、replacement plan、relation status、topology audit 的权威层；人工 relation 不是替换白名单。
- 正式入口或模块契约变更必须同步 `docs/repository-metadata/entrypoint-registry.md`、模块源事实与对应测试。

## 4. 研发视角

阶段 1 只使用既有正式入口和临时 helper 组合验证：

- 不修改正式入口。
- 不修改项目级源事实或模块契约。
- 不将局部人工真值反推为强规则。
- 临时 helper 只落在 `outputs/_work/t10_error2_quality_loop_20260706/tools/`，用于本轮审计和回归。

阶段 2 才允许进入正式代码修复，且每个修复必须满足：

- 有明确根因桶和目标 Segment / RCSDRoad 证据。
- 不越过 T05/T06 已确认字段语义。
- 修改前先确认目标源码/脚本文件体量小于 100KB。
- 涉及入口、契约、源事实时，先读 `docs/repository-metadata/code-boundaries-and-entrypoints.md` 并同轮同步 registry / contract / tests。

## 5. 测试视角

每个根因修复的最小回归链：

1. 20 Segment：`/mnt/e/TestData/POC_Data/T10-Error-2`，跑到 T06 Step3，输出收益与未替换剩余分类。
2. `1885118`：与当前基线对比，确认业务效果无回退。
3. T10 6 case：`1885118 / 605415675 / 609214532 / 706247 / 74155468 / 991176`，确认全链无回退。

核心指标：

- `replacement_unit_success_count`
- `replacement_unit_failure_count`
- `segment_relation_replaced_count`
- `segment_relation_failed_count`
- `topology_connectivity_fail_count`
- `surface_topology_fail_count`
- `rcsd_unreplaced_attribution_count`
- `rcsd_unreplaced_attribution_length_m`

## 6. QA 视角

本轮属于 GIS / 拓扑 / 空间数据闭环，closeout 必须覆盖：

- CRS 与坐标变换：回归 visual/spatial QA 必须显示 CRS 明确，坐标度量在 `EPSG:3857`。
- 拓扑一致性：不得 silent fix；Step3 topology hard fail 不得增加。
- 几何语义可解释性：新增替换或仍未替换的 RCSDRoad 必须能说明 relation、方向、buffer、Segment 消费事实。
- 审计可追溯性：每个 run root、输入 CSV、输出 summary、归因 CSV/GPKG 可定位。
- 性能可验证性：每轮回归保留 summary duration，失败 case 不得被忽略。

## 7. 当前已识别根因桶

基于 20-case baseline 与附件 145 行审计，当前根因桶包括：

- `attachment_row_not_reproduced_in_current_step3_outputs`
- `not_target_scope_current_primary_segment_elsewhere`
- `t06_step1_evidence_or_anchor_blocked`
- `weak_geometry_only_target_scope_review`
- `t06_relation_or_topology_semantic_blocked`
- `consumed_by_other_segment_not_target_scope`
- `already_consumed_by_target_in_current_baseline`
- `t06_postplan_replaced_candidate_only_not_precisely_consumed`

第一优先级修复只覆盖已有源事实授权的两类输入：

- T11 人工正向 relation 进入 T05/T06。
- T10 side-group endpoint candidate 进入 T05 grouping。

其余 Step1 / Step2 硬审计问题必须先证明在现有源事实授权范围内，或升级为模块源事实变更。

## 8. 非目标

- 不把人工 relation 当作 T06 Step2/Step3 替换白名单。
- 不用局部样本反推上游字段语义。
- 不跳过 `graph_consumable=0`、空白、`NULL` 或人工拒绝行。
- 不新增或改变正式入口，除非当前阶段任务明确授权并同轮同步入口登记。
- 不覆盖原始 T05/T06 目录；所有实验输出写入新 run root。
