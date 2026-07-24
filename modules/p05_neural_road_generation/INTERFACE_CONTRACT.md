# P05 方案 A 与历史 M0/M1/M2R/R2/PTO/JSG-PTO 接口契约

## 1. 稳定边界

M0 仅提供 Python 模块 callable，不登记正式 CLI：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    ApprovedExclusion,
    M0Config,
    build_m0_benchmark,
    evaluate_frcsd,
)
```

M0 callable 保持不变。M1 在独立可选训练依赖下新增：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    M1DatasetConfig,
    M1EvaluationConfig,
    M1TrainingConfig,
    build_m1_dataset,
    evaluate_m1_model,
    train_m1_model,
)
```

M1 不登记 repo CLI、root script、T10 stage 或正式主链入口。

M2R 在同一模块边界内新增以下 callable，当前按 SpecKit 任务逐步实现：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    M2RDatasetConfig,
    M2REvaluationConfig,
    M2RSupervisionConfig,
    M2RTrainingConfig,
    build_m2r_dataset,
    build_m2r_supervision,
    evaluate_m2r_oof,
    train_m2r_model,
)
```

M2R 同样不登记 repo CLI、root script、T10 stage 或正式主链入口。

R2 在同一模块边界新增以下已实现 callable；Gate 1/2/3 的结果分别由各自不可变 run 判定：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    R2DatasetConfig,
    R2Gate2Config,
    R2OOFConfig,
    R2OracleConfig,
    R2SlotLimits,
    build_r2_dataset,
    build_r2_oracle_run,
    evaluate_r2_oof,
    train_r2_gate2,
)
```

R2 不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。

PTO-P0 在同一模块边界新增 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    PTOCandidateConfig,
    PTOOracleSolveConfig,
    PTOStrategyReplay,
    build_pto_candidate_run,
    solve_pto_oracle_run,
)
```

PTO-P0 同样不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。

JSG-PTO-P0 在同一模块边界新增以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    JSGP0Config,
    build_jsg_p0_run,
    compile_jsg_case,
    evaluate_jsg_case,
)
```

JSG-PTO-P0 不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。

JSG-PTO-P1 在同一模块边界新增以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    JSGP1CandidateConfig,
    JSGP1OracleConfig,
    build_jsg_p1_candidate_run,
    solve_jsg_p1_oracle_run,
)
```

JSG-PTO-P1 同样不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。

方案 A 在同一模块边界新增以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeABaselineConfig,
    build_scheme_a_baseline_run,
    resolve_scheme_a_fallback,
)
```

方案 A 不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。

Scheme-A-P1 在同一模块边界已提供以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeAP1CandidateConfig,
    SchemeAP1DatasetConfig,
    SchemeAP1OOFConfig,
    build_scheme_a_p1_candidate_run,
    build_scheme_a_p1_dataset,
    run_scheme_a_p1_oof,
)
```

P1 不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target；callable 已实现，但正式结论为 `P05_SCHEME_A_P1_MODEL_NO_GO`，不得解释为模型已通过。

Scheme-A-P2-P0 在同一模块边界已提供以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeAP2CandidateConfig,
    SchemeAP2OracleConfig,
    build_scheme_a_p2_candidate_run,
    solve_scheme_a_p2_oracle_run,
)
```

P2-P0 不训练模型，不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。candidate callable 不接受 truth/dataset 路径；Oracle callable 必须先验证 candidate manifest/hash。正式双跑结论为 `P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`，当前 callable 仅保留候选/Oracle/fallback/RoadGraph 审计能力，不授权 P2-P1 训练或生产接入。

Scheme-A-Dataset-P0 在同一模块边界已提供以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeADatasetP0Config,
    build_scheme_a_dataset_p0_run,
    compare_scheme_a_dataset_p0_runs,
)
```

`SchemeADatasetP0Config` 只接受已冻结的 M0、M2R supervision、方案 A baseline、truth-free PTO candidate/solve、历史 P2 safety run、POC 数据根、输出根、run ID、排除项、T07 mode、数量/门槛与资源预算。正式运行必须将 T07 固定为 `DRIVEZONE_ONLY`，Movement candidate/decision/evaluation 固定为零，并分别审计 T01 SWSD fallback 与非 T01 RCSD/proposal candidate。`build_scheme_a_dataset_p0_run` 在候选 manifest/hash 通过后才连接 label-only truth，输出模块角色、sample/artifact/task、候选来源、Segment/Case Road/Node 可达性、49+2 safety、GIS/资源和全部内容 hash；`compare_scheme_a_dataset_p0_runs` 只比较内容 signature 与 Gate，不比较 wall/RSS 或输出绝对路径。该 callable 不登记正式入口，不训练 scorer，不修改 T01–T12；正式结论 `P05_SCHEME_A_DATASET_P0_GO` 只放行离线数据与候选可达性。

P2-P1在同一模块边界新增以下Python callable，不登记正式入口：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeAP2P1DatasetConfig,
    SchemeAP2P1OOFConfig,
    build_scheme_a_p2_p1_audit,
    build_scheme_a_p2_p1_dataset,
    run_scheme_a_p2_p1_oof,
)
```

`SchemeAP2P1DatasetConfig`只接受冻结Dataset-P0、P1 candidate、PTO candidate/solve、方案A baseline、输出参数和严格范围/hash门禁。builder先从PTO FINAL_NODE truth-free payload按Road endpoint/JunctionUnit冻结`T01_NODE / PROPOSAL_NODE / OMIT` option、ID-free feature及Segment candidate→endpoint/source兼容边，再根据Segment有效标签的Road来源连接条件化Node label并证明100% JunctionUnit compatibility Oracle；PTO Oracle cost只作reachability审计，不直接作Node标签。`SchemeAP2P1OOFConfig`接受已通过dataset、冻结candidate/baseline、seed/训练/阈值/资源和49+2 expected-failure参数；outer held-out Case不参与任何训练统计。OOF只输出score/confidence/uncertainty/anomaly和冻结candidate选择，确定性层不得调用Oracle cost或T06业务规则。`build_scheme_a_p2_p1_audit`比较两次独立OOF的model/score/selection/RoadGraph内容，并审计CRS/geometry/拓扑、单Case scoring和资源；它不改变scorer decision。正式结论为`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`，以上callable只保留离线证据能力，不登记正式入口、不授权生产。

## 2. `M0Config`

| 字段 | 类型 | 约束 |
|---|---|---|
| `poc_data_root` | `Path` | 严格模式下必须解析为 `E:\TestData\POC_Data` |
| `baseline_roots` | `tuple[Path, ...]` | 显式 canonical T10 baseline 根；源码不得写死 run ID |
| `output_root` | `Path` | 新建不可变 run root 的父目录 |
| `run_id` | `str` | 非空且目标目录不得已存在 |
| `split_seed` | `str` | grouped split 稳定 seed |
| `enforce_poc_scope` | `bool` | 正式 M0 必须为 `True`；测试夹具可关闭 |
| `approved_exclusions` | `tuple[ApprovedExclusion, ...]` | 用户确认排除；按 family + business ID 唯一，必须记录非空 reason 和 decision source |

`ApprovedExclusion` 关闭整个样本的全部训练 task mask 并记录审计，不删除样本、split assignment、manifest、label artifact 或 integrity evidence。源码不得内置具体 Case ID。

## 3. Case 输入

扫描器只接受以下登记根：`T03`、`T03_Error`、`T04`、`T04_Error`、`T10`、`T10-Error`、`T10-Error-2`。

- T03/T04：读取 Case `manifest.json` 中 `mainnodeid`、bundle mode、CRS 与校验信息。
- T10 Case：优先读取 Case evidence manifest；缺失时可使用顶层 organization manifest 中该 Case 的显式记录。
- T10 Segment：读取 `t10_case_evidence_manifest.json` 的
  `scope.swsd_segment_id`，不得从目录邻近关系推断。当前 T01 存在同 ID 时直接
  继承目标身份并单列 Road drift；ID 不存在时，只允许以
  `scope.segment_properties.roads` 对当前 T01 `swsd_road_ids` 做无遗漏、
  无重复、无额外 Road 的精确分区 lineage。其它 Segment只作 context input，
  `0.3` 不得进入 label/loss/metric。

缺失 manifest、ID 冲突、hash 冲突或字段语义不满足契约时写入 anomaly，并按任务可用性决定 sample 是否可训练。

## 4. 标签 artifact

canonical T10 标签必须从 baseline `baseline_summary.json` 与每 Case 的 `t10_e2e_case_run_summary.json` 解析，且 Case run 必须为 passed。主标签角色为：

- `t06_frcsd_road`
- `t06_frcsd_node`

辅助角色可包括 `t01_segment`、`t03_nodes`、`t04_nodes`、`t05_intersection_match_all`、`t05_rcsdroad_out`、`t05_rcsdnode_out`、`t06_swsd_frcsd_segment_relation`、`t07_nodes`。

每个 artifact 必须登记 role、绝对路径、SHA-256、source Case、source run summary 和 label weight。路径存在但无法回指指定 `POC_Data` Case 时不得成为标签。

Road/Node artifact 存在但 truth 自身未通过 evaluator integrity gate 时，该 lineage 继续保留用于审计，但样本的 `road_graph` task mask 必须关闭，直至用户重新人工评估或提供新的 canonical run。

用户已确认排除的 truth 使用 `approved_sample_exclusion`，不再计入 pending quarantine；它不得进入任何训练任务或可用 Oracle 分母。

## 5. grouped split

- fold 数固定为 `5`。
- fold 由 `SHA-256(split_seed + "|" + sample_group_id)` 的确定性结果决定。
- 固定视图：fold 0 为 test，fold 1 为 validation，fold 2-4 为 train。
- 同一 `sample_group_id` 的所有版本必须位于同一 fold。

## 6. `evaluate_frcsd`

输入为 candidate Road/Node 与 truth Road/Node 路径。评估顺序：

1. 检查文件、layer、CRS 和字段契约；CRS 不一致时阻断，不隐式重投影。
2. Road/Node 优先按 canonical `id` 一对一匹配。
3. 未匹配 Road 可在显式距离阈值内执行确定性几何 fallback；fallback 原因和距离必须审计。
4. 输出 precision/recall/F1、direction/source 属性准确率、端点误差、Hausdorff/Chamfer 近似和有向拓扑差异。
5. 缺失端点引用、重复 ID、断边、方向冲突和 CRS 冲突进入 hard failures。

评估器只报告差异，不修改输入或执行 silent fix。

## 7. M0 输出

不可变 run root 至少包含：

- `p05_m0_manifest.json`
- `p05_training_samples.csv`
- `p05_label_artifacts.csv`
- `p05_grouped_split.csv`
- `p05_data_anomalies.csv`
- `p05_oracle_evaluation.json`
- `p05_m0_summary.json`
- `p05_m0_report.md`

字段级约束以本轮 SpecKit 的 `contracts/m0-output-contract.md` 为准。

## 8. `M1DatasetConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `m0_run_root` | `Path` | 必须是完整冻结 M0 run，并通过 manifest 中的 output hash 校验。 |
| `output_root` | `Path` | 新建不可变 dataset run 的父目录。 |
| `run_id` | `str` | 非空且目标目录不得已存在。 |
| `seed` | `int` | 数据处理随机种子。 |
| `polyline_points` | `int` | 至少 4。 |
| `entity_guard_hops` | `int` | M1 固定至少 1。 |

`build_m1_dataset` 只消费 M0 `road_graph=true` 样本。`t01_roads` 必须从每个 Case run summary 的显式 handoff 解析并登记 hash。T06 artifact 为 label-only，禁止进入模型特征。

## 9. `M1TrainingConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `dataset_run_root` | `Path` | 必须通过 M1 dataset manifest/hash 校验。 |
| `output_root/run_id` | `Path/str` | 新建训练 run，禁止覆盖。 |
| `seed` | `int` | 模型与训练随机种子。 |
| `hidden_dim/layers/dropout` | `int/int/float` | 默认 `384/6/0.1`。 |
| `epochs/batch_size/learning_rate` | numeric | 全部写入 manifest；不得由固定 test 调整。 |
| `validation_fold/holdout_sample_ids` | optional | 开发集 CV 或 shadow holdout；二者互斥，固定 test 不得作为 holdout。 |
| `train_all_development` | `bool` | 最终模型使用 fold 1-4，并继续移除固定 test 实体及一跳邻域；不读取 test label。 |
| `zero_feature_ranges/min_train_label_weight` | optional | 仅用于开发集消融；必须进入 manifest，不得根据固定 test 调整。 |

`train_m1_model` 使用 PyTorch optional dependency；缺失时必须明确失败，不得自动降级为规则模型。训练 callable 不自动执行固定 test。

## 10. `M1EvaluationConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `dataset_run_root/model_run_root` | `Path` | manifest、checkpoint 和 dataset hash 必须一致。 |
| `output_root/run_id` | `Path/str` | 新建不可变评价 run，禁止覆盖。 |
| `split` | `validation/test` | `test` 必须显式设置 `allow_fixed_test=True`。 |
| `prediction_mode` | `model/keep_all` | 固定 test 使用 `model`，并可在同一次调用设置 `include_keep_all_baseline=True`。 |

`evaluate_m1_model` 在固定 test 上只接受 `final_development_train` checkpoint。模型和 keep-all 必须在一次评价调用中使用同一 dataset、candidate 和 evaluator，避免二次访问固定 test。

## 11. M1 输出与物化边界

M1 dataset、训练和评价产物遵循 `specs/p05-neural-frcsd-m1-20260721/contracts/m1-output-contract.md`。物化器只能执行模型输出的 `DROP/KEEP/SPLIT_1/SPLIT_2/SPLIT_3`、确定性 ID 生成和 schema/hard validation；不得调用 T06 规则补齐无效预测。

`KEEP` 保留输入 Road 几何和 endpoint ID。若该 ID 在全部受控 Node 输入中缺失，物化器可在**不吸附、不移动 Road、不改变 ID**的前提下，使用该 Road 原始几何首末点生成 Node，并记录 `origin=retained_geometry_endpoint`；同一 ID 出现不同坐标时必须进入 materialization failure，不得合并或择近修复。`SPLIT` 子 Road/Node 坐标只来自模型 child geometry 和确定性 ID；空、非有限或零长度几何直接失败。

## 12. `M2RSupervisionConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `m0_run_root` | `Path` | 完整冻结 M0 run，所有登记输出 hash 必须通过。 |
| `output_root/run_id` | `Path/str` | 新建不可变 supervision run。 |
| `enforce_poc_scope` | `bool` | 正式运行必须为 `True`。 |
| `historical_output_roots` | `tuple[Path, ...]` | 只读候选历史输出；只有能回指 Case、run 和人工确认边界时才可成为标签。 |
| `allow_user_confirmed_strategy_replay` | `bool` | 默认 `False`；仅在用户明确确认策略重放结果可作为人工真值时启用。本轮只覆盖 `POC_Data` 的 T03/T04 单点 Case。 |

`build_m2r_supervision` 必须为每个登记样本生成 T03/T04/T05/T06/T07 任务级 `available/unknown/invalid/excluded`。`Error` 目录名不得作为类别，`Unknown` 不得编码为负类。用户确认的 T03/T04 策略重放标签必须同时满足：显式授权开关、显式 run root、输入 manifest SHA-256 精确匹配、正式 `accepted/rejected` 终态和完整 artifact hash；`runtime_failed` 不得解释为业务失败真值。

## 13. `M2RDatasetConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `supervision_run_root` | `Path` | 必须通过 M2R supervision manifest/hash 校验。 |
| `output_root/run_id` | `Path/str` | 新建不可变 dataset run。 |
| `folds` | `tuple[int, ...]` | 使用 M0 business-ID grouped folds。 |
| `include_t07` | `bool` | 只控制可选 T07 Head，不影响必选任务。 |

`build_m2r_dataset` 必须把当前样本目标 artifact 与 T06 reason/status 排除在输入特征外；归一化只使用训练 fold。

## 14. `M2RTrainingConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `dataset_run_root` | `Path` | dataset hash 必须匹配。 |
| `output_root/run_id` | `Path/str` | 新建不可变训练 run。 |
| `seed` | `int` | 写入 manifest/checkpoint。 |
| `held_out_fold` | `int` | OOF fold，不得进入训练统计。 |
| `include_t07` | `bool` | T07 消融开关。 |
| `small_batch_overfit` | `bool` | Head 就绪性门禁模式。 |

`train_m2r_model` 使用任务 mask 和可信权重；每个 Head 的分母、loss 和梯度贡献必须单列。参数量必须位于 `8M~20M`，峰值 VRAM 预算 `16GB`。

## 15. `M2REvaluationConfig`

`evaluate_m2r_oof` 只接受没有训练过目标 group 的 fold checkpoint。free/constrained 必须共用同一 logits；约束白名单以 M2R output contract 为准。所有 intervention 必须写入审计，`content_repair` 恒为 `false`。最终 Road/Node 继续使用 `evaluate_frcsd`，已访问 M1 固定 test 只作历史回归。

## 16. `R2OracleConfig`

| 字段 | 类型 | 约束 |
|---|---|---|
| `m2r_dataset_run_root` | `Path` | 必须通过 M2R dataset manifest/hash，提供 51 个 RoadGraph base/truth lineage。 |
| `output_root/run_id` | `Path/str` | 新建不可变 Gate 1 run，禁止覆盖。 |
| `strict_hashes` | `bool` | 正式运行必须为 `True`。 |
| `emit_reconstructed_gpkg` | `bool` | 正式 Gate 1 必须为 `True`。 |

`build_r2_oracle_run` 读取 base graph 与 label-only truth，生成最终 Road `COPY/UPDATE/SPLIT/CREATE/DROP`、最终 Node `COPY/UPDATE/CREATE/DROP`、T05 阶段 Node edit 和精确 T05 pointer。`CREATE` 用于表达任何无法由 base 引用承载的 truth 对象；oracle materializer 只能执行 payload，不调用 T03-T06 规则。输出必须复用 `evaluate_frcsd` 验证重建。

## 17. R2 edit 与 pointer 合同

- Road `COPY/UPDATE/SPLIT/DROP` 的 `base_road_id` 必须存在；`CREATE` 不得伪造 base 引用。
- `SPLIT` 可以产生任意正数 child；每个 output payload 必须显式包含 ID、geometry、direction、source、端点和 properties。
- Node output 必须在 Road 写出前完成；重复 ID、不同坐标同 ID、缺失 endpoint 引用直接失败。
- T05 pointer 候选来自同一次推理中由 T05 Node edit 生成的候选图，其起点只允许是 raw/T01 base graph；候选键包括 materialized Node `id` 与非零 `mainnodeid`。`rcsdnode_out` 和 truth selected base 只作为 label，必须审计 base existence、generated candidate lineage 与 cardinality，严禁进入输入特征。
- 所有 oracle payload 标记 `label_only=true`，不得登记为模型 input role。

## 18. `R2DatasetConfig` / `R2Gate2Config` / `R2OOFConfig`

R2 dataset 必须消费已通过 Gate 1 的 oracle run，并再次验证其 manifest/hash；input tensor 只来自 raw/T01 base graph，edit/pointer/oracle geometry 只进入 target tensor。训练采用 grouped held-out fold、task mask 和可信权重；T07 固定关闭。模型目标参数量 `20M~50M`，未经重新评估不超过 `60M`，峰值 VRAM `16GB`。

`evaluate_r2_oof` 只接受目标 fold 未参与训练的 checkpoint。free/constrained 共用 logits；constrained 约束仅限 R2 output contract 白名单。最终 Road/Node 使用 `evaluate_frcsd`，`content_repair=false`、`silent_fix=false`。

R2 已完成三道门禁。`build_r2_oracle_run` 与 `train_r2_gate2` 的正式 run 分别通过 Gate 1/2；`evaluate_r2_oof` 完成 51 Case grouped 5-fold 后返回 `gate3_pass=false`。这表示 callable 和审计合同有效，但当前 `R2GraphGenerator` ordinal slot-query 架构不得被解释为可进入生产或继续扩量的模型候选。

## 19. PTO-P0 candidate / solve 合同

`build_pto_candidate_run(PTOCandidateConfig)` 只接受 `PTOStrategyReplay`、允许的 POC 数据根和输出参数。每个 replay 必须登记 family、完整 commit、code root、run root 与期望 Case ID；实现验证 commit、T10 pass 状态、Case scope、raw/T01 与策略输出 hash。历史 T10 replay 内可包含 T07 可选辅助 stage，但 T07 不产生 PTO candidate 或 selection。原 Case 缺少 runner manifest 时可以使用实验区 source-path wrapper，但全部 external input 必须仍位于允许的 `POC_Data` 根并逐文件哈希。candidate run 不接受 R2 oracle/truth 参数，manifest 必须为 `truth_input_count=0`、`truth_derived_candidate_count=0`。

`solve_pto_oracle_run(PTOOracleSolveConfig)` 必须先验证 candidate manifest/hash，再读取已通过的 R2 Gate 1 label-only oracle。Oracle cost 为候选赋值并生成 objective/lower bound/gap 证书；物化只执行选中 edit，不调用 T03-T06 规则。通用约束白名单为 action domain、每个 base group 唯一选择、唯一输出 ID、base/endpoint 引用、有限非空几何与合法生成状态。任何候选缺失、泄漏、非 OPTIMAL、非零 gap、relaxation、content repair 或 silent fix 都必须显式失败。

## 20. JSG-PTO-P0 truth / evaluator / compiler 合同

`JSGP0Config` 只接受冻结 R2 Oracle run、与该 scope/hash 精确匹配的正式 PTO candidate run、POC 数据根、输出根、run ID、显式排除和严格 hash/范围开关。PTO candidate run 只用于读取其已登记的 T01/T05/T06 replay lineage；R2 Oracle 的 T06/RoadGraph 仍是 label-only compiler truth。正式运行必须严格限制到 `E:\TestData\POC_Data` 的 51 Case，排除项不得出现在分母。源码不得内置具体 Case 清单；Case scope 由冻结 manifest 与参数决定。

`build_jsg_p0_run(JSGP0Config)` 读取已声明的 T01/T05/T06/R2 label-only lineage，输出 canonical `JSGCaseTruth`、对象覆盖、review/anomaly、compiler 和 RoadGraph 评价。自动转换不得推断未确认字段语义；多 THROUGH、Connector access 不唯一、Terminal/loop 证据不足必须显式 `REVIEW/UNKNOWN`。

`evaluate_jsg_case` 只验证 schema、ID、引用、端点、显式 loop、方向、环岛、THROUGH、Connector、Movement、CRS 与 canonical signature，不修改输入。`compile_jsg_case` 只验证并读取 JSG 中已声明的 label-only carrier realization，生成/物化现有 R2 edit IR；不得调用 T01-T06 策略、补路、吸附、重连或内容修复。

正式 run 必须记录全部输入/输出 SHA-256、环境、逐 Case wall/CPU/RSS 和两个独立 run 的 deterministic signature；`label_only=true`、`content_repair=false`、`silent_fix=false`。

P0 正式 Run A/B 已通过：51/51 JSG 往返和 compiler 精确，hard failure=0；两轮 semantic/compiled/provenance signature 完全一致。该完成状态不改变 callable 的 label-only 边界，也不授权 JSG 候选生成、PTO 选择、scorer 或生产入口。

## 21. JSG-PTO-P1 candidate / Oracle 合同

`JSGP1CandidateConfig` 只接受 truth-free RoadGraph PTO candidate run、输出根、run ID、POC 数据根、显式排除和 hash/范围开关；不得包含 P0/R2 truth path。`build_jsg_p1_candidate_run` 必须验证上游 manifest 为 `truth_input_count=0`、`truth_derived_candidate_count=0`，从 T01/registered proposal lineage 生成 finite JSG/PTO-B candidate，并在 Oracle 前冻结全部输出 hash。

`JSGP1OracleConfig` 接受已冻结 P1 candidate run、P0 JSG truth run、R2 Oracle run、输出参数和严格门禁。`solve_jsg_p1_oracle_run` 先验证 candidate manifest/hash，再读取 label-only truth 计算 cost；truth 不得增加、删除、改写 candidate。PTO-A/PTO-B 非 OPTIMAL、gap 非零、candidate 缺失、carrier 不可行、compiler hard failure、relaxation/content repair/silent fix 均失败。

正式 run 必须分开记录 candidate signature 与 selection signature、逐 Case coverage/certificate/compiler/GIS 结果、历史 replay 成本和 P1 增量资源。P1 成功只放行候选/Oracle 合同，不代表 scorer 或生产能力。

## 22. JSG-PTO-P2 dataset / OOF 合同

P2 在同一模块边界新增以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    JSGP2DatasetConfig,
    JSGP2OOFConfig,
    build_jsg_p2_dataset,
    run_jsg_p2_oof,
)
```

`JSGP2DatasetConfig` 必须接受冻结 P1 candidate run、P1 Oracle label run、M0 run、输出根、run ID 和严格 hash/Case 数量参数。`build_jsg_p2_dataset` 必须验证三者 scope/hash、P1 candidate 零泄漏、M0 fold/weight 和排除项，再生成 ID-free feature token、fold、label-only truth equivalence、权重与 forbidden-token audit。candidate/label ID 只用于 join，不进入 scorer feature。

`JSGP2OOFConfig` 必须接受已冻结 P2 dataset、原 candidate runs、P0/R2 truth run、输出参数和 V0/V1 配置。`run_jsg_p2_oof` 对每个 held-out fold 只使用其它 fold label 拟合 V1；V0/V1 共用相同 PTO-A/PTO-B、compiler 和 evaluator。所有 score 必须有 confidence/uncertainty/source/model signature，并能由 feature token 与 fold model 重建。

P2 不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。任何 held-out leakage、候选缺失、infeasible、非零 gap、compiler/GIS hard failure、relaxation/content repair/silent fix 必须保留为失败，不得回退 Oracle cost。

## 23. JSG-PTO-P3 context / neural OOF 合同

P3 在同一模块边界新增以下 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    JSGP3DatasetConfig,
    JSGP3OOFConfig,
    build_jsg_p3_context_dataset,
    run_jsg_p3_oof,
)
```

`JSGP3DatasetConfig` 只接受冻结 P1 candidate run、P2 dataset run、输出根、run ID 与严格 hash/Case/fold/group/candidate 数量参数。`build_jsg_p3_context_dataset` 通过 ID 连接候选组和 dependency graph，但输出 context token 不得含 Case/business/object/candidate/group ID、绝对坐标、truth、Oracle cost 或 truth signature；`feature_uses_truth=false`。

`JSGP3OOFConfig` 接受 P3 context dataset、P2/P1/P0/R2 冻结 run、seed/训练/资源参数与输出参数。outer held-out Case 不得参与 vocabulary、class weight、inner validation、early stopping 或任何训练统计；score 完成后才读取 held-out label 评价。模型只输出统一 `candidate_id/cost/confidence/uncertainty/score_source/model_signature/context_signature` 合同，PTO-A/PTO-B、compiler 和 evaluator 不得改变。

正式运行必须输出每 fold/seed 的 vocabulary、train/inner/held-out Case、checkpoint/hash、参数量、training history、OOF score、JSG/Review/ECE、PTO/RoadGraph/GIS 与资源。P3 不登记 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target；任何 leakage、infeasible、非零 gap、hard failure、relaxation/content repair/silent fix 必须保留为失败。

## 24. 方案 A baseline / label / fallback 合同

`SchemeABaselineConfig` 只接受冻结 JSG-P0 run、M0 run、POC 数据根、输出根、run ID、Case 数、排除项和严格 hash/范围开关。实现从 JSG-P0 lineage 读取 T01 Segment/Road/Node 与 T06 relation truth；旧 JSG truth 只提供已冻结 Junction/普通 relation/PhysicalMovement 证据，不得把旧 `SegmentConnector` 或 PTO-A 选择作为当前骨架。

`build_scheme_a_baseline_run` 必须逐 Case输出全部 T01 Segment，保留 `pair_nodes/junc_nodes/roads/segment_type`，将 `advance_right` 规范为含 `source_segment_access/target_segment_access` 的 `ADVANCE_RIGHT Segment`。T01 未显式给出 access 时，只能按独立 Road 的唯一有向端点与端点处唯一普通 Segment owner形成；任一侧不唯一则 `access_valid=false`、输出 `RealityChangeClue`，不得按几何邻近猜测。策略状态只按登记合同映射为三态；未知状态 hard fail。Segment 标签只允许 `USE_RCSD/KEEP_SWSD/MIXED_CARRIER/REVIEW_FALLBACK`，Movement 标签只允许 Road/Node carrier realization；骨架存在性不进入可学习目标。

`resolve_scheme_a_fallback` 是无 I/O 纯函数。Segment 失败只回退该 Segment，不自动改变或回退任何 PhysicalMovement；Junction冲突回退关联全部 Segment。Movement 仅因自身候选缺失、低置信或 carrier 冲突回退；carrier 确实共享或影响 Junction 内部拓扑时才升级为 Junction fallback，否则只回退该 Movement。SWSD access、独立 Road或端点引用不合法时输出失败和 `RealityChangeClue`，不得补造。

正式 run 不写 GPKG、不修改输入，只输出冻结 skeleton、strategy baseline、carrier labels、clues、fallback plans、summary/manifest/hash。必须为 `skeleton_mutation_count=0`、`content_repair=false`、`silent_fix=false`，并满足对应 SpecKit 输出合同。

方案 A 正式 Run A/B `p05_scheme_a_baseline_20260722_12/_13` 已通过：51 Case、8,863 Segment、474 ADVANCE_RIGHT、24,779 PhysicalMovement；五类业务 signature 一致，artifact hash 全量复核通过。Segment 标签为 `USE_RCSD=2,190 / KEEP_SWSD=6,619 / MIXED_CARRIER=14 / REVIEW_FALLBACK=40`；Movement 标签为 `USE_RCSD=21,328 / REVIEW_FALLBACK=3,451`。Segment fallback 不遮蔽或改写 Movement label；仅 Movement 自身/Junction fallback 可 mask Movement。修正前 `_10/_11` 只保留历史证据。该合同不包含生产入口授权。

## 25. Scheme-A-P1 candidate / dataset / OOF 合同

`SchemeAP1CandidateConfig` 只接受已通过的 Scheme A baseline run、登记的零 truth strategy proposal/replay、POC 数据根、输出根、run ID、排除项和严格 hash/范围参数。candidate builder 必须在读取 label 前生成 Segment/Movement carrier candidates，并记录 `truth_input_count=0`、`truth_derived_candidate_count=0`、`absolute_coordinate_feature_count=0`。

`SchemeAP1DatasetConfig` 接受冻结 candidate run、Scheme A baseline label run、M0 split/weight 与输出参数。dataset builder 必须先验证 candidate manifest/hash，再执行 label-only join；可用 Segment/Movement exact candidate reachability 必须为 `100%`，Case/business/object/candidate/group ID、truth、Oracle、relation status/reason 与绝对坐标不得进入 feature。

`SchemeAP1OOFConfig` 接受冻结 dataset/candidate/baseline run、seed/训练/阈值/资源参数和输出参数。outer held-out Case 不得参与 vocabulary、normalization、class weight、inner validation、early stopping或阈值选择。模型只输出 candidate cost/confidence/uncertainty 与 anomaly probability；确定性执行器负责 hard gate、最小闭包 fallback 和 RoadGraph 物化，`skeleton_mutation_count=0`、`content_repair=false`、`silent_fix=false`。

RoadGraph materializer 对同 ID 的 T01/proposal payload 只允许执行“carrier 语义等价”判定：二维几何以及 T01 Road/Node 核心字段在 ID 类型归一后必须精确一致；proposal 独有的审计扩展字段不参与冲突判定。等价 payload 只保留已选候选的确定性原 payload，不合并或改写属性，并逐 ID 记录 `semantically_equivalent_payload_coalesce_*` 审计；几何、端点、方向、`mainnodeid/subnodeid` 或任一核心字段不同仍为 hard conflict 并 fallback。

Scheme-A-P1 正式 run `p05_scheme_a_p1_oof_formal_20260722_01` 已完成并判定 `P05_SCHEME_A_P1_MODEL_NO_GO`。Gate 0/4/5 通过，Gate 1/2/3 失败；seed 17重放 `_02` 的 model/score/prediction/fallback/RoadGraph 内容一致。该合同不包含生产入口或 T01–T12 接入授权。

RoadGraph 终态只允许 `LEGAL`、`EXPECTED_FAIL` 或非预期 `FAIL`。冻结 expected-failure manifest 精确包含 `T10:74155468 -> missing Node 953982` 与 `T10:609214532 -> missing Node 987665`；两者必须生成 `RealityChangeClue`、`publish=false`，不得用补点、吸附或 payload 修复转换为 `LEGAL`。其余49 Case必须为 `LEGAL`，任何 expected-failure 集合漂移或额外 `FAIL` 都使 Gate 4失败。Case终态不得把全 Case Segment决策覆盖为fallback；只有 RoadGraph audit 的`failure_group_ids`命中对象执行局部失败，其它具有有效 Dataset-P1 label 的 Segment继续进入 scorer metric。

## 26. Scheme-A-Dataset-P1 Segment-scoped 标签合同

P05 暴露只读 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeADatasetP1Config,
    build_scheme_a_dataset_p1_scope,
)
```

`SchemeADatasetP1Config` 只接受冻结 Dataset-P0、Scheme A baseline、
P2-P3-P0、POC_Data、输出和严格范围/hash/资源参数。builder 不训练模型、不读写
geometry、不修改历史 run；输出 package lineage、8,863 Segment唯一标签范围、
expected-failure 双层资格、历史指标失效账本、summary/manifest/hash。

`label_eligible=true` 时 `label_weight=0.7`；`CONTEXT_ONLY_MASKED` 时
`label_weight=null`、`context_input_weight=0.3`，并且不得进入 carrier/clue
label、loss、threshold、calibration 或 metric。正式 Run A/B
`p05_scheme_a_dataset_p1_20260723_01/_02` 已通过，decision 为
`P05_SCHEME_A_DATASET_P1_GO`。该 callable 不登记 CLI、root script、T10 stage、
`__main__.py` 或 Makefile target。

## 27. Scheme-A-P2-P3-P2 Dataset-P1 scorer 重基线

P05 暴露内部 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeAP2P3P2Config,
    run_scheme_a_p2_p3_p2_oof,
)
```

`SchemeAP2P3P2Config`组合冻结的P2-P3-P0配置、Dataset-P1根、输出run和可选
reference run。runner必须精确读取Dataset-P1 manifest/hash，只有
`label_eligible=true`的6,275个Segment可以进入训练、inner validation、threshold、
calibration和metric；2,588个`CONTEXT_ONLY_MASKED` Segment必须生成
`dataset_p1_context_only_fallback`，proposal/effective target均为`KEEP_SWSD`，
`accepted=false`。`failure_group_ids`只允许把登记对象改为
`dataset_p1_localized_expected_failure`，不得按Case级联。

正式输出至少包含scope application、eligible score/decision/evaluation、
all-segment decision、effective selection、RoadGraph、closure、fold、metric、
feature audit、summary和manifest。正式Run 04/05已完成，decision均为
`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`，规范化signature一致且Run 05 reference
match=true。该callable不是CLI、root script、T10 stage、`__main__.py`或Makefile
target，不构成在线/生产接口。

## 28. Scheme-A-P2-P3-P3 硬安全资格与残余可分性审计

P05 暴露内部 Python callable：

```python
from rcsd_topo_poc.modules.p05_neural_road_generation import (
    SchemeAP2P3P3Config,
    run_scheme_a_p2_p3_p3_audit,
)
```

`SchemeAP2P3P3Config`只接受冻结P2-P3-P2配置/正式run、方案A baseline、输出、
可选reference run和残余对象ID。runner必须校验全部manifest/hash，并将
Dataset-P1 eligible group按`case_key + object_id`与`segment_inventory.csv`
严格1:1 join。

硬门只允许在`segment_type=ADVANCE_RIGHT`且显式`access_valid=false`时触发，
输出`accepted=false`、`clue_predicted=true`、
`reason=advance_right_access_invalid`。字段缺失、身份错配、非Review命中或分母
漂移必须hard fail；未命中decision必须保持原对象与内容不变。硬门不得读取T03、
T04、T05、T06终态、标签或Case目录语义。

残余审计按原held-out fold和每seed训练Case独立建立202维标准化近邻，记录candidate
score/utility margin、exact signature碰撞和近邻真值构成；truth只用于审计输出，
不得进入推理。runner不训练模型、不调阈值、不读取或写入geometry、不修改T01–T12，
不登记CLI、root script、T10 stage、`__main__.py`或Makefile target。

## 29. Scheme-A-P2-P3-P4 Dataset-P1-first 真值重基线

内部配置为`SchemeAP2P3P4Config`，内部callable为
`run_scheme_a_p2_p3_p4_audit`。输入必须显式提供Dataset-P1、方案A baseline、
P1 candidate、PTO candidate、历史P2-P1 dataset、P2-P3-P2、P2-P3-P3、输出根、
run ID和可选reference run；所有manifest、声明output与SHA-256必须验证。

执行顺序必须为：

1. 按`case_key + object_id + group_id`将8,863个Segment与Dataset-P1 scope精确
   1:1 join；
2. 6,275个`label_eligible=true`对象保留原Scheme-A监督真值；
3. 2,588个`CONTEXT_ONLY_MASKED`对象标签贡献为0，输入权重保持0.3，安全物化
   使用唯一`KEEP_SWSD` candidate；
4. 仅在上述scope冻结后运行Road endpoint/JunctionUnit条件化Node真值与共享
   payload冲突闭包。

runner只重建Segment/Node标签层；P2-P1 feature、payload、compatibility edge和
P2-P3-P3 decision/effective/RoadGraph必须按hash只读复用。输出至少包含
scope-first Segment/Node labels、初始Node冲突、Junction fallback closure、
旧/新label delta、metric rebaseline、residual reinterpretation、dataset/summary/
manifest与artifact manifest。context-only不得进入label/loss/threshold/metric。

本阶段decision仅允许
`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`
或`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_NO_GO`。GO只表示真值闭包顺序和残余
解释通过，不表示模型GO，不授权训练、调阈值、生产接入、T01–T12修改、正式入口、
Movement或geometry处理。

## 30. Scheme-A-P2-P3-P5 Scope-first 重训合同

内部配置为`SchemeAP2P3P5DatasetConfig`和`SchemeAP2P3P5Config`，内部callable
为`build_scheme_a_p2_p3_p5_dataset`与`run_scheme_a_p2_p3_p5_oof`。它们不登记
CLI、root script、T10 stage、`__main__.py`或Makefile target。

Dataset callable必须：

1. 验证P4与历史P2-P1 manifest/output hash；
2. 仅重写Segment/Node labels，按hash复用candidate feature、payload、group和
   compatibility工件；
3. 输出8,863 Segment、28,240 Node，且
   `6,275 eligible + 2,588 context-only`、eligible target为
   `4,486 KEEP_SWSD + 1,749 USE_RCSD + 40 REVIEW_FALLBACK`；
4. 保证context supervision、duplicate group和truth candidate missing均为0；
5. Dataset A/B signature一致。

OOF callable必须从头训练原P2-P3-P0网络的3 seeds × 5 Case folds，推理只使用
冻结202维truth-free证据；随后应用40个`ADVANCE_RIGHT access_valid=false`硬门，
使用scope-first Node/Junction真值闭包物化RoadGraph。每seed整体和每fold均须同时
满足零错误/Review自动接受、carrier safety recall=1.0、总体与USE coverage均
不低于0.50，以及clue recall=1.0、precision不低于0.80、macro-F1不低于0.85和
clue-only全捕获。context-only只允许确定性`KEEP_SWSD`，不得进入训练或指标。

正式decision仅允许`P05_SCHEME_A_P2_P3_P5_MODEL_GO`、
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`或
`P05_SCHEME_A_P2_P3_P5_AUDIT_NO_GO`。正式结果为
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`：审计与RoadGraph门通过，carrier coverage
和clue门失败。该callable及结论不授权生产入口、自动替换SWSD、Movement、
geometry处理或T01–T12改动。

## 31. Scheme-A-P2-P3-P6 双层失败归因合同

内部配置为`SchemeAP2P3P6Config`，内部callable为
`run_scheme_a_p2_p3_p6_audit`。它不登记CLI、root script、T10 stage、
`__main__.py`或Makefile target。

callable必须只读验证P5 OOF、scope-first dataset和202维evidence的manifest、
size与SHA-256，并唯一join eligible decision/evaluation/score/effective。
输出必须分开：

1. scorer decision层：硬门后、RoadGraph原子阻断前的逐对象判断；
2. final publication层：RoadGraph合法性与`EXPECTED_FAIL`阻断后的发布结果；
3. clue error层：逐seed/fold/Case的FP、FN、probability、threshold和margin；
4. evidence层：相反标签exact collision及held-out-fold train-only top-K邻域。

完整审计分母为每seed6,275；safe coverage分母排除40 Review，为6,235。
`T10:609214532`与`T10:74155468`在scorer层只允许登记failure group局部失败，
final publication层必须如实记录1,954个eligible整Case原子阻断，禁止再把后者
描述为“非目标级联为零”。

正式decision只允许
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`或
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_AUDIT_NO_GO`。归因GO要求同时证明calibration
与representation问题，只放行下一阶段技术路线讨论；不改变
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`，不授权训练、调阈值、生产接入、
T01–T12修改、Movement或geometry处理。

## 32. Scheme-A-P2-P3-P7 T06前表征与Clue校准审计合同

内部配置为`SchemeAP2P3P7Config`，内部callable为
`run_scheme_a_p2_p3_p7_audit`。它不登记CLI、root script、T10 stage、
`__main__.py`或Makefile target，不训练模型、不拟合calibrator、不调阈值。

输入必须只读验证P6、Dataset-P0、P2-P1 dataset和P2-P2-P2-P0 evidence的
manifest/size/SHA-256。允许推理来源仅为T01、T07 `DRIVEZONE_ONLY`、truth-free
proposal/compatibility和既有base OOF统计；T03/T04/T05/T06继续label-only。
历史202维工件不得改写；P7必须排除14个实际非零Movement命名维及其28个邻域派生
维，输出602维：

1. 188维movement-free base；
2. 377维Case内compatibility-neighborhood；
3. 37维T01平移/旋转不变相对几何与共享节点邻域。

输出必须包含`movement_free_representations.jsonl`、`feature_contract.json`、
`source_audit.json`、`neighborhood_audit.json`、`clue_calibration_audit.json`、
summary、report和manifest。ID只作lineage join，不得进入feature；geometry write、
coordinate transform、skeleton mutation、truth/T03–T06/Movement feature必须为0。

正式decision只允许
`P05_SCHEME_A_P2_P3_P7_REPRESENTATION_GO_NEXT_TRAINING_REVIEW`、
`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`或
`P05_SCHEME_A_P2_P3_P7_AUDIT_NO_GO`。任一decision均不自动授权训练；当前正式
结果为`CURRENT_SOURCE_NO_GO`。

## 33. Scheme-A-P2-P3-P8 T03/T04 推理来源合同审计

内部配置为`SchemeAP2P3P8Config`，内部callable为
`run_scheme_a_p2_p3_p8_audit`。它不登记CLI、root script、T10 stage、
`__main__.py`或Makefile target，不训练模型、不拟合calibrator、不调阈值。

输入必须只读验证P7、P6、Dataset-P0和T03/T04模块源事实hash。T03/T04当前
`model_input=false/label_only=true`必须原样保留。Segment只允许通过Case-local
T01 `junc_nodes`关联T03/T04 `target_id/mainnodeid`；空间join、最近邻、T05补关系
和cross-Case join禁止。无来源必须输出`NOT_APPLICABLE` mask，不得编码为负样本。

promotion候选只允许正式T05 handoff枚举、required/support/selected对象计数和
surface形式合法性布尔量。ID、坐标、路径、free-text reason、review-only、
T05/T06终态、truth/label/oracle/fold统计及Movement全部禁止进入候选。T04
`junction_type/scene_type`保留为上下文候选，但carrier source signature对
`merge/diverge`方向不变，不改变T04业务类型。

输出必须包含`core_artifact_inventory.csv`、`source_fact_ledger.jsonl`、
`segment_applicability.jsonl`、字段合同、carrier/Clue/source audit、summary、
report和manifest。正式decision只允许
`P05_SCHEME_A_P2_P3_P8_T03_T04_SOURCE_GO_PROMOTION_REVIEW`、
`P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`、
`P05_SCHEME_A_P2_P3_P8_T03_T04_SOURCE_NO_GO`或
`P05_SCHEME_A_P2_P3_P8_AUDIT_NO_GO`。当前结果为carrier-only partial GO；
任一decision都不自动提升字段或授权训练、生产接入。

## 34. P9 Carrier-only Promotion Overlay

用户已批准P8白名单在P05内部进入carrier branch。该overlay不修改历史Dataset-P0
role contract：T03/T04工件仍是原始label-only中间成果，只有经过P8字段过滤、
Case-local `junc_nodes`关联和applicability mask后的副本可作为P9 carrier输入。

Clue branch不得读取source字段或absence；`source_applicable=false`时Treatment
source residual必须严格为0。T01骨架、access硬门、Node/Junction decoder、
fallback和RoadGraph安全合同不变。

P9内部配置为`SchemeAP2P3P9Config`，内部callable为
`run_scheme_a_p2_p3_p9_oof(config)`；不注册repo CLI、script或T10 stage。输出必须
包含Control/Treatment score、decision、evaluation、effective、RoadGraph、fold、
source contract、metrics、summary和manifest。正式decision只允许
`P05_SCHEME_A_P2_P3_P9_CARRIER_MODEL_GO_CLUE_BLOCKED`、
`P05_SCHEME_A_P2_P3_P9_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED`、
`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`或
`P05_SCHEME_A_P2_P3_P9_AUDIT_NO_GO`。当前正式结果为
`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。

## 35. P12R AdvanceRight 条件化真值与候选上限审计

内部配置为`P12RConfig`，内部callable为
`run_scheme_a_p2_p3_p12r_audit`。它不注册CLI、root script、T10 stage、
`__main__.py`或Makefile target，不训练模型、不修改T01–T12、不写geometry。

推理允许输入仅为T01 Segment/Road/Node与原始RCSD Road/Node。T06 relation、
final Road/Node、advance-right attachment/closure/topology audit和P11人工接受集
只能作为label-only证据；T05不得为提右端点提供anchor label，T06终态不得成为
candidate或feature。

每个`AdvanceRightRealizationUnit`必须输出Case/fold/object、两侧相邻普通Segment、
required/realized source、truth plan、SWSD/RCSD Road lineage、splice、
attachment、fallback、RealityChangeClue和candidate oracle证据。终态
`topology_supplement_from_swsd`仍按SWSD来源解释；audit中的
`replacement_segment_ids`不得直接解释为提右附着Segment。

输出必须包含`advance_right_realization_truth.jsonl`、
`advance_right_candidate_ceiling.jsonl`、
`advance_right_attachment_audit.jsonl`、`fold_metrics.json`、`metrics.json`、
`p12r_summary.json`、`p12r_manifest.json`、`artifact_manifest.json`和
`validation_report.md`。正式decision只允许
`P05_SCHEME_A_P2_P3_P12R_GO`、
`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`、
`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_NO_GO`或
`P05_SCHEME_A_P2_P3_P12R_AUDIT_NO_GO`。

当前正式结果为
`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`：总体candidate
oracle recall为`377/396=0.952020`，最差Case-grouped fold为
`21/24=0.875`。该结果不授权训练或自动发布。

## 36. P12R-R1 Endpoint/Junction 条件化候选

内部配置为`P12RR1Config`，内部callable为
`run_scheme_a_p2_p3_p12r_r1_audit`。它不注册CLI、root script、T10 stage、
`__main__.py`或Makefile target，不训练模型、不写geometry、不修改T01–T12。

Phase 1只允许读取冻结T01 Segment/Road/Node、原始RCSD Road/Node和P12R登记的
Case/fold清单，构造并冻结候选、endpoint证据和对象清单；P12R truth、T06
relation/final Road/Node及人工裁决只能在candidate signature冻结后进入Phase 2
Oracle。T05不得提供提右anchor label，T06终态不得成为candidate或feature。

Treatment可在P12R 5m local Control之上增加Case-local原始RCSD提右Road bundle。
component以精确Node连通形成；bundle合并只允许顺序端点`<=1m`或平行source/source
与target/target端点均`<=5m`；boundary incident普通Road到T01相邻普通Segment
Road的候选关联距离必须`<=10m`。orientation必须唯一；不同owner严格平局为
`AMBIGUOUS`并拒绝自动加入。所有阈值只服务candidate discovery。

输出必须包含`advance_right_endpoint_candidates.jsonl`、
`advance_right_candidate_delta.jsonl`、`endpoint_evidence_audit.jsonl`、
`fold_metrics.json`、`metrics.json`、`r1_summary.json`、`r1_manifest.json`、
`artifact_manifest.json`和`validation_report.md`。正式decision只允许
`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`、
`P05_SCHEME_A_P2_P3_P12R_R1_RECALL_NO_GO`、
`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_QUALITY_NO_GO`或
`P05_SCHEME_A_P2_P3_P12R_R1_AUDIT_NO_GO`。

当前正式结果为`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`：Control/Treatment
recall=`0.952020/0.979798`，最差Treatment fold=`0.916667`，P95/max候选数
`4/12`，相对Control gain/loss=`11/0`。该结果不授权训练或自动发布。

## 37. P13-P0 AdvanceRight Candidate-set Scorer

内部配置为`P13P0Config`，内部callable为
`run_scheme_a_p2_p3_p13_p0_oof(config)`。它不注册CLI、script、T10 stage、
`__main__.py`或Makefile target，不修改T01–T12，不决定Movement或写geometry。

Phase 1重放并验证R1 candidate signature，生成50维truth-free feature并冻结
feature signature；Phase 2才读取R1/P12R label。所有transform、checkpoint、
candidate/object/safety threshold必须fold-local。模型固定3 seeds × 5 Case folds，
参数量30万至150万；当前实现为480,739参数。

输出必须包含`feature_schema.json`、`candidate_features.jsonl`、
`candidate_labels.jsonl`、`fold_inventory.json`、15个确定性NPZ checkpoint、
`training_summaries.jsonl`、`candidate_scores.jsonl`、
`object_decisions.jsonl`、`fold_metrics.json`、`metrics.json`、
`p13_p0_summary.json`、`p13_p0_manifest.json`、`artifact_manifest.json`和
`validation_report.md`。

正式decision只允许`P05_SCHEME_A_P2_P3_P13_P0_MODEL_GO`、
`P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`、
`P05_SCHEME_A_P2_P3_P13_P0_SAFETY_NO_GO`或
`P05_SCHEME_A_P2_P3_P13_P0_AUDIT_NO_GO`。

当前正式结果为`P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`：raw exact/model
minus Local Control=`0.646907/-0.033505`，最差fold=`0.363636`，
unsafe/review/unreachable RCSD auto publish=`14/2/1`，accepted coverage
`0.017677`。该结果不授权自动发布或继续同构训练。
