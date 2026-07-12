# T01/T06 RCSD Road 唯一归属与 Segment 替换定位升级 Plan

**Branch**: `codex/t06-rcsd-ownership-20260711` | **Date**: 2026-07-11 | **Spec**: `spec.md`

## 1. Summary

在 T01 增加不参与锚定的提右 Segment，在 T06 增加覆盖全部原始 RCSD Road 的 ownership 层；把现有二度连通补充升级为独立 multi-segment connectivity group；收紧 path-corridor group，禁止 Step2 rejected Segment仅凭 group probe 计为 Segment replaced；保持六 Case 2,484 个 Step2 正式输入可追溯，并只允许有显式错误证据的基线 Segment 少量回退。

## 2. Technical Context

**Language/Version**: Python 3.10.x
**Primary Dependencies**: GeoPandas、Shapely、Fiona/Pyogrio、pandas
**Storage**: GPKG/CSV/JSON sidecar
**Testing**: pytest；T10 Case runner；本轮一次性审计脚本
**Target Platform**: repo 标准 Python 环境与内网同构运行环境
**Project Type**: GIS/topology batch pipeline
**Performance Goals**: 记录 1885118 与六 Case 各阶段耗时；不得出现异常数量级增长
**Constraints**: 无新 CLI/入口；无 silent fix；单源码文件 <100KB；1885118 先行；Step2 输入集合不丢失，最终替换结果的回退必须逐项有证据
**Scale/Scope**: 六 Case 16,347 条原始 RCSD Road、5,733 个 T01 Segment、2,484 个 Step2 可替换 Segment

## 3. Constitution Check

- 分层源事实：SpecKit 工件先定义变更，验证通过后同步 T01/T06 源事实；通过。
- Brownfield 先研究：`research.md` 已完成六 Case 与 1885118 深审计；通过。
- 非破坏性迁移：现有 relation 与未替换归因保留兼容字段，新 ownership 成为正式指标来源后再收口旧口径；通过。
- 中文文档：通过。
- 入口治理：不新增 CLI、scripts、tools、Makefile 目标；通过。
- 文件体量：拟修改文件均低于 100KB；新增逻辑优先新小模块；通过。
- 五职责视角：本计划显式覆盖产品、架构、研发、测试、QA；通过。

## 4. 产品视角

- SWSD Segment 是业务归属主对象；RCSD Road 属性不能反向决定 SWSD 单元。
- 普通 Segment、提右 Segment、多 Segment connectivity 分开建模。
- 普通 Segment 的锚定完整性与替换正确性优先于替换数量。
- RCSD Road 使用率与 Segment 替换率分开统计。
- unresolved 是需持续压缩的例外，不是归因兜底。

## 5. 架构视角

### 5.1 T01 提右 Segment

新增内部组件 `advance_right_segments.py`：

1. 只读取正式 SWSD 提右属性；
2. 在未构段提右 Road 子图中形成稳定 Road 组；
3. 生成 `segment_type=advance_right`、稳定 id、Road 列表和构建审计；
4. 不生成普通 Pair/Junc 锚定要求；
5. 在 Step6 聚合前接入，不改变入口。

### 5.2 T06 ownership 层

新增 `rcsd_road_ownership.py`，汇总：

- 普通 Segment 正式 Step2 Road；
- 提右 Step3 选中 Road；
- multi-segment connectivity Road；
- 最终未使用 Road；
- reality change/unresolved 证据。

以原始 `rcsdroad_out.id` 为唯一键，copy-on-write split 只写入 `final_road_ids`。

### 5.3 普通 Segment 替换边界

- Step2 replaceable 继续是普通 Segment 正式替换白名单；
- Pair/Junc 完整锚定是硬门禁；
- `group_probe_status=passed` 不能覆盖 source Segment rejected；
- 当前 path-corridor group 的 Road union 只作为 connectivity/ownership 候选或审计证据，不直接提升 Segment 指标。

### 5.4 多 Segment connectivity

重构 `step3_unreplaced_bridge_fallback.py`：

- 先生成独立 group，不直接把 Road 所有权追加到多个 Segment；
- 线性组、两端挂接、非受保护锚点、候选可消歧时可执行；
- 非线性、开放端点、锚点触达、歧义保留 blocked audit；
- T09 兼容期仍可在 relation 中暴露相关 carrier，但 owner 只在 group/ownership 表中出现一次。

### 5.5 归因迁移

现有 `t06_step3_unreplaced_rcsd_attribution` 由 ownership ledger 派生或对照：

- 现有六类汇报口径保留兼容；
- 正式 owner 不再以最近几何主 Segment作为最终真相；
- class 1 需区分 reality change、connectivity 和 unresolved；
- class 6 需逐项证据耗尽，不允许通用 fallback。

## 6. 研发视角

### 6.1 拟新增文件

- `src/rcsd_topo_poc/modules/t01_data_preprocess/advance_right_segments.py`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_road_ownership.py`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/multi_segment_connectivity.py`
- 对应小型测试文件。

### 6.2 拟修改文件

- T01：`skill_v1_pipeline.py`、`step6_segment_aggregation.py`、`schemas/summary` 相关现有文件；
- T06：`replacement_plan_rows.py`、`group_replacement_audit.py`、`step3_group_replacement.py`、`step3_unreplaced_bridge_fallback.py`、`step3_segment_replacement_runner.py`、`rcsd_unreplaced_attribution.py`、`schemas.py`；
- 测试：replacement plan、group atomic、second-degree fallback、unreplaced attribution、T01 pipeline。

任何源码写入前重新记录当前字节数；若实际文件接近或超过 100KB，立即按 AGENTS §1.4 停机并给出拆分计划。

### 6.3 实施阶段

1. 先测试并实现 T01 提右 Segment；
2. 在 1885118 重跑 T01/T06，验证 979 个 Step2 输入完整读取，并审计基线回退与后置 topology 回退；
3. 实现 ownership ledger 的只读汇总，不改变替换；
4. 在 1885118 验证 ownership 覆盖/唯一性并迭代 unresolved；
5. 拆分 multi-segment connectivity 与 Segment relation；
6. 收紧 Step2 外 path-corridor Segment replacement；
7. 重新验证 1885118 的 28 个对象和 topology；
8. 扩展到其余五 Case；
9. 最后更新源事实与稳定 contract。

## 7. 测试视角

### 7.1 T01

- 提右 Road-only 连通组形成 advance_right Segment；
- 普通/提右 Road 不混合；
- 提右 Segment 无 Pair/Junc 锚定；
- T06 提右来源判断排除 advance_right Segment 自身，只消费两端相邻普通 Segment 的 replaced/retained 状态；
- mixed SWSD 提右在 replaced 侧执行基于已选 RCSD Road 的几何一致挂接，显式 split/reuse mainnode 关系拥有最高优先级；
- id 稳定、审计完整；
- 现有普通 Segment 单元测试不回退。

### 7.2 T06 ownership

- 每个原始 RCSD Road 恰好一条 ownership；
- copy-on-write split 保持原始到 final 映射；
- single owner 唯一；
- connectivity group 只落一次；
- reality change/unresolved 门禁；
- ownership 与 final/unreplaced partition 一致。

### 7.3 replacement plan

- Junc 缺失/无效的 rejected Segment 不发布 `replace_segment`；
- blocked group closure 不发布 Segment replacement；
- candidate group 只能在 connectivity 规则满足时发布 `include_connectivity`；
- Step2 formal replaceable 不被 group 调整阻断。

### 7.4 Case 顺序

固定顺序：

1. `1885118` 聚焦单元与 Case 回归；
2. `1885118` 大阶段完成并通过输入完整性、ownership、显式回退证据与 topology gate；
3. `605415675 / 609214532 / 706247 / 74155468 / 991176` 六 Case 汇总回归。

不得提前用六 Case 平均值掩盖 1885118 的具体回退。

## 8. QA 视角

必须输出：

- 六 Case Step2 冻结 id 差分；
- Step2 RCSD Road 数量/里程差分；
- Segment replacement、RCSD Road used、advance_right、connectivity 分层指标；
- 67 个 Step2 外成功对象逐项根因与新处置；
- ownership missing/duplicate/unresolved/reality change 分布；
- final/unreplaced partition 完整性；
- CRS、无效几何、拓扑 hard fail、summary 一致性；
- 运行耗时与环境定位。

基线指针不自动刷新。只有 1885118 与六 Case 全部通过且用户明确授权后才进入基线注册。

## 9. Project Structure

```text
specs/t01-t06-rcsd-road-ownership-20260711/
├── spec.md
├── research.md
├── data-model.md
├── plan.md
├── tasks.md
└── contracts/
    └── ownership-output-contract.md

src/rcsd_topo_poc/modules/t01_data_preprocess/
├── advance_right_segments.py
├── skill_v1_pipeline.py
└── step6_segment_aggregation.py

src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/
├── rcsd_road_ownership.py
├── multi_segment_connectivity.py
├── replacement_plan_rows.py
├── group_replacement_audit.py
├── step3_group_replacement.py
├── step3_unreplaced_bridge_fallback.py
├── step3_segment_replacement_runner.py
└── rcsd_unreplaced_attribution.py
```

## 10. 风险与控制

| 风险 | 控制 |
|---|---|
| 提右 Segment 改变普通 Step2 分母 | `segment_type` 路由，普通冻结集合逐 id 对比 |
| 提右 Segment 自身被误当成 retained side | mixed 判定只统计非提右普通 Segment，并用两侧 replaced/retained 组合测试锁定 |
| mixed attachment 或 relation refresh 产生最终叶子/断路 | final topology hard gate、显式 attachment mainnode 优先级和六 Case逐对象回算 |
| 直接质量回退造成相邻 replaced Segment 二次级联回退 | hard-gate plan 记录直接失败 node；在第二轮回退前用当前 topology、有效 T05 唯一 root、Patch/T04 阻断和 12m 门禁做受限 mainnode 收口 |
| connectivity 被重新算成 Segment replaced | 独立 action/owner/metric，Segment 指标固定排除 |
| path-corridor 关闭后 RCSD Road used 回退 | 先转 ownership/connectivity，再调整 Segment 状态；逐对象根因 |
| unresolved 变成垃圾桶 | 证据耗尽字段、候选、人工清单、每轮单调不增加 |
| T09 carrier 消费断裂 | 保留 relation 兼容引用，新增 ownership 字段而不改 T09 入口 |
| summary 继续漂移 | 从最终落盘文件回算并设置一致性 QA gate |
| 性能下降 | 以连通域/空间索引分组，1885118 先量测再扩六 Case |

## 11. Complexity Tracking

本轮跨 T01/T06 是业务边界本身要求：T01 必须先补齐提右 Segment，T06 才能建立完整 owner。将全部逻辑放在 T06 会违反 SWSD Segment 主对象原则；仅修改 T01 又无法解决 RCSD ownership、path-corridor 与指标分层。因此跨模块变更不可避免，但不扩大到 T05/T09 正式接口修改。
