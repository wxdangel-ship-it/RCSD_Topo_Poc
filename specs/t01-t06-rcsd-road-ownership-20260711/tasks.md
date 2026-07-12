# T01/T06 RCSD Road 唯一归属与 Segment 替换定位升级 Tasks

## Phase 1：隔离与现状研究

- [x] T001 在 `E:\Work\RCSD_Topo_Poc__wt_t06_rcsd_ownership_20260711` 建立分支 `codex/t06-rcsd-ownership-20260711`。
- [x] T002 核验最新六 Case 正式基线 `t10_full_96b0ea5_20260710_060735` 和六个 Case id。
- [x] T003 深审计 `1885118` 的 Step2 replaceable、replacement plan、Step3 relation、未替换归因和 GIS 图层。
- [x] T004 冻结 `1885118` 的 979 个及六 Case 合计 2,484 个 Step2 可替换 Segment。
- [x] T005 识别 `1885118` 的 28 个及六 Case合计 67 个 Step2 外成功替换 Segment。
- [x] T006 量化 path-corridor 多 Segment引用、二度连通 fallback、未替换归因置信度和 T01 提右缺口。
- [x] T007 生成 `research.md / spec.md / data-model.md / plan.md / analyze.md / contracts/`。

## Phase 2：T01 提右 Segment（US1）

- [x] T008 写入任何 T01 源码前，记录目标文件当前字节数并确认低于 100KB。
- [x] T009 [US1] 在 `tests/modules/t01_data_preprocess/test_advance_right_segments.py` 增加失败测试：纯提右组构段、普通/提右不混合、无 Pair/Junc、稳定 id、审计字段。
- [x] T010 [US1] 在 `src/rcsd_topo_poc/modules/t01_data_preprocess/advance_right_segments.py` 实现提右 Road-only Segment 构建。
- [x] T011 [US1] 在现有 T01 pipeline / `step6_segment_aggregation.py` 接入提右 Segment，不新增入口。
- [x] T012 [US1] 更新 T01 summary/schema，输出提右 Road、Segment、跳过与冲突统计。
- [x] T013 [US1] 运行 T01 聚焦单元测试并确认新增场景通过；全量 T01 的 5 个 Windows path/CRLF 失败已在主工作区复现为既有问题。
- [x] T014 [US1][QA] 重跑 `1885118` T01→T06，验证 979 个 Step2 可替换输入完整读取；提右 Segment 单列；最终 929 个 Segment 替换相对旧 937 的回退已按错误基线与 topology gate 审计。

## Phase 3：RCSD Road ownership 基础层（US2/US6）

- [x] T015 写入任何 T06 源码前，记录目标文件当前字节数并确认低于 100KB。
- [x] T016 [US2] 在 `tests/modules/t06_segment_fusion_precheck/test_rcsd_road_ownership.py` 增加失败测试：一条原始 RCSD Road恰好一条 owner、split 映射、candidate 不等于 owner。
- [x] T017 [US2] 在 `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_road_ownership.py` 实现 ownership ledger 聚合与完整性校验。
- [x] T018 [US2] 在 `schemas.py` 增加 ownership 与 connectivity 输出 schema。
- [x] T019 [US2] 在 Step3 runner 接入 ownership 与 construction audit 输出。
- [x] T020 [US6][QA] 在 `1885118` 验证 6,435 条 ownership、重复 0、缺失 0。
- [x] T021 [US2] 对 `1885118` unresolved 收敛；最终 `unresolved_exception=0`。

## Phase 4：多 Segment connectivity（US5）

- [ ] T022 [US5] 增加 connectivity group 单元测试：跨两个 Segment 的线性桥接、调头/平行连接、unattachable、开放端点、非线性、锚点触达、歧义。
- [x] T023 [US5] 在 `rcsd_road_ownership.py` 内建立 multi-Segment connectivity group，让一组 RCSD Road只属于一个 group owner，未新增重复职责文件。
- [x] T024 [US5] 重构 `step3_unreplaced_bridge_fallback.py`，不再把 ownership 直接复制到多个 Segment unit；保留 relation carrier 兼容引用。
- [x] T025 [US5] connectivity supplement 计 RCSD Road 指标，不计 Segment 指标。
- [x] T026 [US5][QA] 在 `1885118` 验证 97 条 connectivity RCSD Road进入 Road 指标、88 个 connectivity group 不计 Segment 指标。

## Phase 5：普通 Segment 替换边界与 67 对象根因（US3/US4/US6）

- [x] T027 [US3] 修改 replacement plan 测试：source 非 formal replaceable、Junc 缺失/无效、blocked group closure 均不得发布 `replace_segment`。
- [x] T028 [US3] 收紧 replacement plan source Segment 门禁，path/group 只保留 connectivity/ownership 证据。
- [x] T029 [US3] Step3 不再让 path/group corridor 扩大普通 Segment 替换集合，connectivity 单列。
- [x] T030 [US4] 增加并验证严格 2b：只允许主干完整、附属侧路缺失；主干缺失/断连必须 hold。
- [x] T031 [US3][QA] 在 `1885118` 及六 Case逐对象表中确认 Junc 缺失/无效对象不再替换。
- [x] T032 [US3][QA] 回归 required topology 与方向性 group 样例，输出 retain/connectivity/ownership 的逐项根因。
- [x] T033 [US6] 生成六 Case 67 个对象的正式 `baseline_status / root_cause / current_owner_types / new_business_action / metric_effect` 表。

## Phase 6：未替换归因迁移（US2/US6）

- [ ] T034 [US2] 修改 `rcsd_unreplaced_attribution.py`，以 ownership ledger 为正式 owner 真相，几何主 Segment只保留候选证据。
- [ ] T035 [US2] 明确 reality change 证据门禁，拆出 connectivity 和 unresolved。
- [ ] T036 [US2] 对 unresolved 强制候选、尝试规则、失败证据、下一 owner 与人工复核字段。
- [ ] T037 [US6] 保留现有 5+1/六类汇报兼容映射，但禁止从兼容 class 反推正式 owner。
- [ ] T038 [US6][QA] 在 `1885118` 对 1,206 条未替换 RCSD 逐项验证 owner 类型、证据和无重复。

## Phase 7：指标、summary 与 GIS/拓扑 QA

- [x] T039 分离普通 Segment、提右 Segment、RCSD Road、connectivity group 指标。
- [ ] T040 从最终落盘 GPKG/CSV 回算 summary，增加 summary/actual 一致性 hard gate。
- [ ] T041 验证 CRS、空/无效几何、原始到 split Road 映射和 topology hard fail；禁止 silent fix。
- [ ] T042 记录 `1885118` ownership/connectivity/Step3 性能并处理异常数量级回退。
- [x] T043 完成 `1885118` 大阶段 gate：Step2 输入集合、ownership 唯一、28 个 Step2 外旧成功对象根因、RCSD Road used、Segment 指标、topology 明确允许项。

## Phase 8：六 Case 回归

- [x] T044 按固定五 Case顺序运行 `605415675 / 609214532 / 706247 / 74155468 / 991176`。
- [x] T045 验证六 Case 2,484 个 Step2 可替换输入完整读取；最终 Segment 替换允许显式证据支持的少量回退，RCSD Road 指标与 Segment 指标分离审计。
- [x] T046 验证 16,347 条原始 RCSD ownership 覆盖 100%、重复 owner 0、缺失 0、unresolved 0。
- [x] T047 验证六 Case 190 条 connectivity RCSD Road计入 Road used，242 个 connectivity group 不计 Segment 替换。
- [x] T048 完成 67 个 Step2 外旧成功 Segment 的根因与新处置审计；1,755 个关联 RCSD Road 引用全部找到当前 owner。
- [ ] T049 输出六 Case性能、CRS、几何、拓扑、summary 一致性报告。

## Phase 9：源事实同步与收口

- [ ] T050 更新 T01 `SPEC.md / architecture/* / INTERFACE_CONTRACT.md`，正式启用提右 Segment 类型与字段。
- [x] T051 更新 T06 `SPEC.md / INTERFACE_CONTRACT.md`，统一 Junc required 语义、ownership、connectivity、提右独立处理与指标边界；本轮未改 architecture 文档。
- [ ] T052 更新 T06 风险/质量文档，删除与新业务冲突的 path-corridor Segment promotion 描述。
- [x] T053 检查所有源码文件体量并同步 `code-size-audit.md`；本轮源码均低于 100KB。
- [x] T054 运行 T01/T06 聚焦测试、1885118、六 Case最终回归，并记录既有 Windows-only 测试失败。
- [x] T055 未刷新 baseline 指针、未合并、未推送。

## Phase 10：正式 Final F-RCSD Topology 指标

- [x] T056 审计现有 `Topology fail` 定义、计数差异和稳定主键折叠问题。
- [x] T057 更新 T06 源事实、接口契约与 SpecKit，定义 `segment_transition / independent_attachment` 两类正式 fail。
- [x] T058 实现逐行 final topology 分类、稳定对象 key 和正式 summary 指标。
- [x] T059 将 topology-safe rollback 从全部 audit fail 切换到正式 final topology fail 集合。
- [x] T060 增加分类、去重、提右 lineage/endpoint 和 summary 一致性测试。
- [x] T061 先回归 `1885118`，再按固定顺序回归其余五 Case并输出新旧指标对照。

## 执行依赖

- Phase 2 完成并通过 1885118 后才能进入 ownership 与 replacement 行为变更。
- Phase 3 ownership 只读输出先落地，证明覆盖与唯一性后，才能改变 path-corridor 和 bridge 行为。
- 每个大阶段先 `1885118`；只有 T043 完成后才运行六 Case。

## Phase 11：Final Topology 质量修复

- [x] T062 审计并确认 31 个 T06 必修、14 个可接受 RCSD 边界叶子和 1 个 inherited SWSD 输入叶子。
- [x] T063 修复提右来源判定，排除 advance_right Segment 自身对两侧 replaced/retained 状态的干扰。
- [x] T064 修复 T01 提右 Segment direct-context 将 mixed attachment 误收紧为 1m 的兼容问题。
- [x] T065 保护显式 split/reuse attachment mainnode，禁止 retained relation refresh 覆盖。
- [x] T066 将 accepted RCSD native boundary leaf 从正式 final topology 指标移除并保留审计。
- [x] T067 对无法闭合的 replaced/retained Segment transition 执行最终 hard gate 与受控回退。
- [x] T068 增加来源、mixed attachment、mainnode 优先级、accepted exception 和 transition hard gate 回归测试。
- [x] T069 按 `1885118 -> 605415675 -> 609214532 -> 706247 -> 74155468 -> 991176` 实跑，证明 31 个必修对象清零并更新体量审计。

## Phase 12：基线回退逐对象审计与级联误回退修复

- [x] T070 将基线 `2,365` 与当前结果逐 Segment 对齐，识别 20 个净回退中的 18 个基线正式质量失败和 2 个无基线失败证据的二轮级联回退。
- [x] T071 在 hard-gate plan 中记录 `final_topology_hard_gate_failure_node_ids`，以直接失败节点和受影响邻接节点分离原始质量回退与级联 fail。
- [x] T072 实现受限 T05 权威 transition closure，在第二轮回退前恢复 `609214532` 的 2 个级联误回退 Segment，并输出逐节点审计。
- [x] T073 按固定六 Case 顺序复跑，最终 Segment replaced 为 `929 / 250 / 653 / 297 / 85 / 133`，净回退 18；逐 Segment 原始证据落盘。
- [x] T074 对 RCSD Road used 集合做逐 Road 基线差异审计：79条 lost Road 直接属于18个质量回退 Segment，1条为两端关联 Segment 均回退后的从属 connectivity 失效；无基线质量证据的 Road 指标损失为0。
- 任何 Step2 冻结集合回退、Junc 锚定语义冲突或源码跨 100KB 均按 AGENTS 硬停机处理。
