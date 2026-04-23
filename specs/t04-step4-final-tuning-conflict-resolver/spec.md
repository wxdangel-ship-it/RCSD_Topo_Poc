# T04 Step4 Final Tuning Conflict Resolver

## 背景

本轮只处理 `T04 Step4` 最后阶段的冲突仲裁层，不进入 `Step5-7`，不重做候选空间，不重做主证据发现，不重做正向 RCSD 原始召回主链路。

当前既有事实：

- `T04` 已运行时独立于 `T02`
- `Step1-4` frozen baseline 已建立，主证据主链路已通过人工目视审计
- 当前 accepted `Anchor_2` 基线为 `8 case / 13 event unit`
- `17943587` 已确认存在 same-case RCSD claim 歧义，需要纳入本轮

## 本轮目标

为 `T04 Step4` 新增一个 second-pass final resolver，在不破坏当前 accepted baseline 的前提下：

1. 先做主证据冲突仲裁
2. 再做正向 RCSD claim 冲突仲裁
3. 最后做联合一致性检查
4. 输出可审计的 conflict inventory / resolution summary / baseline compare

## 范围内

### 产品边界

- 只修 `Step4 final tuning / 冲突仲裁层`
- 重点覆盖 `17943587`
- 非冲突单元冻结
- same-case 先于 cross-case
- 先降 claim，不先降 support
- 只有“主证据冲突 + RCSD 冲突”双重同向成立时，才允许 evidence reopen
- RCSD 冲突不得单独推翻已正确的主证据

### 架构边界

- 保留现有 first-pass `build_case_result()` 语义
- 新增 second-pass resolver 层
- batch 级 cross-case 决策必须在全量 `case_result` 构建后执行
- 输出层只消费 finalized `case_result`

### 研发边界

- 不重做 `pair-local / structure_face / throat / middle`
- 不放大候选搜索空间
- 不重新引入 `T02` runtime 依赖
- 不通过 hardcode winner / hardcode case id 伪造结果

### 测试边界

- 保留现有 `Anchor_2` accepted 8 case / 13 unit 主证据冻结
- 保留现有 `A + primary_support + positive_rcsd_present=true` accepted 面
- 新增冲突 resolver 的 unit / real-case / batch compare 守门

### QA 边界

- `review_state=STEP4_REVIEW` 不是失败条件
- 必须继续产出完整 `run root / case / event_unit` 固定文件集
- `review_index / review_summary / step4_event_interpretation / step4_candidates` 必须自洽

## 冲突类型定义

### 主证据冲突

#### 可允许共享

- 同一上层 evidence object，但不同 `local_region_id`
- 不同 `point_signature`
- `localized_evidence_core_geometry` 不重叠
- 同轴但 `|Δevent_chosen_s_m| > 5m`
- pair-local 语义可解释为两个独立位置

#### 软冲突

- coarse zone 有交叠
- 上层 object 相同
- 位置接近，但 core 不实质重叠
- 仍可能通过 same-case 重选化解

#### 硬冲突

- `local_region_id` 相同
- `point_signature` 相同
- `localized_evidence_core_geometry` 明显重叠
- 同 `event_axis_branch_id` 且 `|Δevent_chosen_s_m| <= 5m`

### 正向 RCSD claim 冲突

#### 可共享

- 共享 trunk / corridor 性质的 `selected_rcsdroad_ids`
- 共享部分 RCSDRoad，但 `required_rcsd_node` 不同
- 共享部分 aggregated unit road，但 role mapping 指向不同 pair-local arms

#### 软冲突

- 同 `required_rcsd_node`
- 或 `selected_rcsdroad_ids` 高重叠
- 但主证据未冲突，且仍可在现有 support 内重选 unique claim

#### 硬冲突

- 同 Case 内多个 unit claim 同一 `required_rcsd_node`
- 且 pair-local 邻近或明显重叠
- 且 role mapping / event-side 解释互斥
- 或主证据也无法支持“同一 RCSD 节点被两个 unit 合理占用”

## 正式仲裁顺序

1. 先主证据冲突仲裁
2. 再正向 RCSD claim 冲突仲裁
3. 最后联合一致性检查

约束：

- RCSD 冲突默认不能单独推翻主证据
- 只有主证据冲突与 RCSD 冲突双重同向时，才允许 evidence reopen
- same-case 先解，cross-case 后解
- 非冲突单元不进入 resolver

## 基线保护线

必须冻结并保护：

- `primary_candidate_id`
- `primary_candidate_layer`
- `selected_evidence_state`
- `review_state`
- `positive_rcsd_present`

当前 accepted 面还必须继续守住：

- `8 case / 13 event unit`
- `positive_rcsd_support_level=primary_support`
- `positive_rcsd_consistency_level=A`
- `required_rcsd_node` 非空

允许的变化只有：

- 冲突 component 内的 `required_rcsd_node` / claim 审计字段发生显式、可解释的变更
- 且不得造成 silent regression

## 验收

本轮结束前必须能明确回答：

1. same-case evidence conflict 是否已稳定可判
2. same-case RCSD claim conflict 是否已稳定可判
3. `17943587` 是否已收敛
4. accepted baseline 是否无主证据回退
5. 当前 positive RCSD recall correctness 是否保持
6. Step4 final tuning 是否可以结束
7. 是否仍不进入 Step5
