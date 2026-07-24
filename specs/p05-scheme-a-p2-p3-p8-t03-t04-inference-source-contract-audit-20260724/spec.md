# P05-Scheme-A-P2-P3-P8：T03/T04 推理来源合同审计

## 1. 状态与授权

- 状态：已授权，实施中
- 授权日期：2026-07-24
- 用户选择：P7 后续方案 1，审计 T03/T04 推理来源
- 唯一实施工作树：
  `E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 当前 T03/T04 角色：继续 `label-only`，本阶段不得直接提升
- 训练、拟合、调阈值：禁止
- T01–T12 实现与接口：不修改
- Git：不提交、不推送
- Movement：忽略

本阶段承接
`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`，只回答 T03/T04 的哪些正式输出
在 T06 之前已真实存在、可稳定复现、可按冻结 T01 Junction—Segment 关系映射，并
对 P7 残余问题提供新增事实。任何正向结论只放行来源角色二次评审，不自动改变
Dataset-P0 或模型输入合同。

## 2. 阶段目标

1. 核验51个 eligible Case中 T03/T04 正式工件的存在性、hash、CRS、生成时点和
   T05 handoff 语义；
2. 建立不包含ID、坐标、路径、free-text reason、review-only字段和T05/T06终态的
   source whitelist；
3. 只通过冻结 T01 `junc_nodes` 执行 Case-local Segment 关联；
4. 检验 P7 稳定 carrier wrong 是否获得跨 Case 同签名正确训练证据；
5. 检验全部稳定 Clue 错误是否都具有 T03/T04 适用证据；
6. 判定 T03/T04 来源可完整提升、仅 carrier 部分提升，或当前不适合提升。

## 3. 冻结业务语义

1. T03 是常规虚拟路口锚定；surface accepted 不等于 relation success。
2. T04 是复杂分歧/合流虚拟路口锚定；Reference Point、surface scenario 与
   relation evidence 分层解释。
3. T03/T04 的 `relation_state/status_suggested` 是面向 T05 的正式 handoff，
   位于 T06 之前；它们不是 T06 carrier 真值。
4. T03/T04 的策略结果若后续获准作为推理来源，意味着 P05 Road scorer 运行在
   T03/T04 之后，不表示神经网络独立替代 T03/T04。
5. Segment 只允许通过冻结 T01 `junc_nodes` 关联 T03/T04 `target_id/mainnodeid`；
   不得使用空间吸附、最近邻或 T05 relation 补 join。
6. 无适用 T03/T04 Junction 的 Segment必须用 applicability mask表达，不能编码为
   negative、success或failure。

## 4. 字段角色

### 4.1 可审计候选

- T03：`junction_type/template_class/association_class/step7_state/
  surface_candidate_present/status_suggested/relation_state`及
  required/support/excluded对象的数量。
- T04：`junction_type/scene_type/final_state/swsd_relation_type/
  rcsd_profile/has_c_unit/surface_candidate_present/status_suggested/
  relation_state`及required/selected对象数量。
- T04 surface summary：
  `surface_scenario_type/section_reference_source/reference_point_present`
  和形式合法性布尔量。

上述字段都保留为字段级 promotion 候选；但用于 Gate 2 比较“carrier 安全状态同类
证据”的 signature 对 T04 `merge/diverge` 方向不变。也就是说，
`junction_type/scene_type` 仍可作为模型上下文，不参与拆分
`no_related_rcsd` 等 carrier relation-state 身份。该归一化只用于来源可分性审计，
不改写 T04 业务类型。

### 4.2 明确禁止

- `target_id/case_id/mainnodeid/anchor_id/base_id_candidate/patch_id`原值；
- SWSD/RCSD坐标、geometry path、audit path、review PNG path；
- free-text `reason`、review-only状态；
- T05/T06终态、truth、label、Oracle、fold统计；
- Movement及其派生字段。

禁止字段可保留在lineage/source ledger中，但不得进入可提升字段清单或数值特征。

## 5. 五类职责视角

### 产品

- 成功标准是明确字段级来源角色，不要求强行得到完整GO。
- carrier可用与Clue可用必须分开判定。

### 架构

- T03/T04继续位于T05/T06之前；P05只读消费正式handoff，不调用T05/T06。
- applicability、source module和多Junction聚合必须显式。

### 研发

- 只新增P05内部审计schema/callable、测试和SpecKit。
- 不新增CLI、script、T10 stage或长期入口。

### 测试

- 覆盖字段白名单/黑名单、Case-local `junc_nodes` join、无适用证据mask、
  多Junction聚合、稳定对象同签名train-only审计和阶段decision。

### QA

- 输入、hash、CRS、source docs、字段、join、输出和运行环境可追溯。
- geometry只允许读取CRS/schema；write、transform、silent fix均为0。
- Run A/B规范化signature一致。

## 6. 验收门禁

### Gate 0：来源与时点

- P7 decision精确为
  `P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`；
- Dataset-P0 decision为`P05_SCHEME_A_DATASET_P0_GO`；
- 51个eligible Case的T01/T03/T04登记路径和核心正式工件全部存在且hash可冻结；
- T03/T04正式源事实均声明输出面向T05，T05/T06输入计数为0；
- T03/T04当前`model_input=false/label_only=true`事实如实保留。

### Gate 1：字段与关联合同

- whitelist与blacklist覆盖所有被读取字段；
- ID/坐标/path/reason/review/T05/T06/truth/Movement feature计数均为0；
- 6,275个eligible Segment全部输出applicability ledger；
- 只用Case-local T01 `junc_nodes`关联，空间join与cross-Case join均为0；
- 无证据和多Junction均显式审计，不做silent merge。

### Gate 2：carrier新增事实

- 稳定carrier wrong
  `T10:609214532 / 505101583_506183080`必须命中正式T03/T04来源；
- 其source signature不得读取truth或held-out Case统计；
- T04 `merge/diverge` 只作为上下文，不能把相同 carrier relation-state 拆成不同
  安全状态；
- held-out-fold之外至少有2个完全同签名对象；
- 同签名训练对象必须全部为`KEEP_SWSD`且至少1个`clue=true`；
- 同签名`USE_RCSD`训练对象必须为0。

### Gate 3：Clue来源覆盖

- P7的2个稳定FP、4个稳定FN均逐对象审计；
- 只有6/6全部具备T03/T04 applicable evidence且无相反语义冲突，才允许Clue来源GO；
- 未适用对象不得用absence直接推断Clue。

### Gate 4：确定性与资源

- Run A/B signature一致且Run B reference match=true；
- wall `<=10min`、CPU RAM `<=8GiB`、GPU=0；
- 完整P05回归通过；新增源码/测试均小于100KB；
- 未新增入口，未修改T01–T12。

## 7. 阶段决策

- carrier与Clue来源门均通过：
  `P05_SCHEME_A_P2_P3_P8_T03_T04_SOURCE_GO_PROMOTION_REVIEW`
- carrier门通过、Clue门失败：
  `P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`
- 审计可信但carrier门失败：
  `P05_SCHEME_A_P2_P3_P8_T03_T04_SOURCE_NO_GO`
- 来源/hash/字段/join/确定性/资源任一审计门失败：
  `P05_SCHEME_A_P2_P3_P8_AUDIT_NO_GO`

任何决策均不自动修改T03/T04的`label-only`角色，不授权训练、生产接入或自动替换
SWSD。正向或部分正向结论必须由用户另行批准字段级promotion合同。
