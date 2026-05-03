# T04 RCSD Alignment Implementation Gap Audit

本文件汇总产品、架构、研发、测试、QA 五个角色的只读审计结论，作为后续正式编码任务输入。

## 1. Product Audit

### Conclusion

需求总体自洽。最新口径已经明确：

- `rcsd_alignment_type` 是 Step4 进入 Step5 前的唯一 RCSD 对齐结果。
- `rcsd_match_type` 只是兼容粗分类，不能替代精细业务判定。
- 六类正常构面场景加 `no_surface_reference` 防御性兜底。
- complex/multi 不是独立场景，而是 unit-level 构面后做 case-level 合并。
- 30-case baseline 不仅守 final state，还要守主证据、Reference Point、RCSD/SWSD section reference、surface scenario、Step6 guards、nodes 写回。

### Product Gaps

- 代码没有实现 `rcsd_alignment_type` 字段；review row 仍只有 `rcsd_match_type`。
- partial RCSD 与完整 RCSD 语义路口会被粗分类吞掉。
- `ambiguous_rcsd_alignment` 不存在，候选排序后直接取第一名存在静默错选风险。
- partial / road-only / no-RCSD 的截面边界没有按 `rcsd_alignment_type` 精细实现。
- 负向掩膜缺少 unrelated SWSD nodes、RCSDNode 等分通道审计。
- 导流带本体作为负向掩膜的硬约束未充分闭环。
- Step6 存在放宽 Step5 约束的 relief 风险。
- complex/multi 缺少 case-level RCSD 对齐证明。

### High-Risk Cases

- `698389 / 760277 / 807908`：有主证据 + RCSD 语义路口，必须走 `Reference Point + RCSD semantic junction`。
- `807908 / 768675`：需要防止把其他 RCSD 语义路口链路或无关 SWSD roads 并入。
- `785629`：导流带主证据 + 无 RCSD 语义路口，不能降级成 SWSD-only 或错误 RCSDRoad fallback。
- `785731 / 795682 / 765050`：无主证据 + 无 RCSD 语义路口，应使用 SWSD section window，不得 accepted 的 `no_surface_reference`，不得虚拟 Reference Point。
- `505078921`：complex multi-unit，必须守 unit required RCSD node 和 case-level 不混聚。
- `706629 / 706347`：SWSD-only，无虚拟 Reference Point。
- `760984 / 788824`：无主证据但有 RCSD section reference。
- `765170 / 768680 / 823826`：细缝、小洞、relief 风险。
- `607602562 / 760598 / 760936 / 857993`：当前正确 rejected，不应为提高 accepted count 静默转 accepted。

## 2. Architecture Audit

### Conclusion

现有 Step4/Step5/Step6 架构局部可承载，但正式口径不足。六场景框架、SWSD-only 修复、Step5 拆分、Step6 guards 已有基础；但还不能稳妥承载唯一 `rcsd_alignment_type`、unit/case 两级复杂路口对齐、负向掩膜双通道、六场景截面边界。

### Architecture Gaps

- `rcsd_alignment_type` 没有落成代码模型。
- partial junction 与 road-only fallback 被粗分类压扁。
- ambiguous alignment 没有一等状态。
- `T04CaseResult` 缺少 case-level alignment aggregate。
- 负向掩膜已有 `unrelated_swsd_mask_geometry` 与 `unrelated_rcsd_mask_geometry` 雏形，但缺少 node/road 分通道和来源审计。
- Step5/Step4 边界不是冻结 alignment object，而是多个旧字段即时推断。
- `polygon_assembly.py` 仍是体量和职责风险点，后续新增逻辑前应拆出 guard/result/relief。

### Recommended Boundaries

- `rcsd_alignment.py`：定义 `RcsdAlignmentType`、候选、唯一选择、ambiguous reason、positive ids、unrelated ids、section reference eligibility。
- `case_rcsd_alignment.py`：聚合 unit alignment，判断 complex/multi 的 case-level alignment 与跨 RCSD 对象冲突。
- `surface_scenario.py`：降为纯映射层，只接受 `has_main_evidence + rcsd_alignment_type + swsd_context`。
- `support_domain_masks.py`：承载 SWSD/RCSD/divstrip/forbidden 分通道负向掩膜。
- `polygon_assembly_guards.py`、`polygon_assembly_relief.py`、`polygon_assembly_models.py`：从 Step6 拆出 guard、relief、result dataclass。

## 3. Development Audit

### Conclusion

当前实现没有满足“Step4 输出唯一 `rcsd_alignment_type`，Step5/6 只消费唯一对齐结果”的新契约。实现仍停留在旧的 `rcsd_match_type / positive_rcsd_* / required_rcsd_node / selected_rcsd*` 组合判断。

### Development Gaps

- `T04EventUnitResult`、`PositiveRcsdSelectionDecision`、`T04ReviewIndexRow`、`step4_candidates.json` 均没有 `rcsd_alignment_type`。
- `surface_scenario.py` 只定义粗分类 `rcsd_junction / rcsdroad_fallback / none`。
- `support_domain_builder.py` 通过 `section_reference_source / fallback_rcsdroad_ids / selected_rcsdroad_ids` 推导 active RCSD，不是消费唯一对齐结果。
- Step6 没看到重选候选，但存在局部替换/放宽 `case_forbidden_domain`、`cut_barrier_geometry`、`case_allowed_growth_domain` 的路径。

### Recommended Implementation Order

- 在 Step4 RCSD 选择层新增正式 `rcsd_alignment_type` 枚举。
- 将字段落到 `PositiveRcsdSelectionDecision`、`T04EventUnitResult`、candidate audit、review index、Step4 JSON。
- 将 `aggregated_units[0]` 的隐式取第一名升级为唯一消歧与 ambiguous 输出。
- 重写 `surface_scenario.py` 输入口径，以 `rcsd_alignment_type` 为主。
- 让 Step5 只消费 Step4 的 alignment object、positive ids、negative mask ids。
- 将 Step6 relief 审计为 cleanup within constraints；若要扩大 allowed 或扣减 forbidden/cut，应上移 Step5。

## 4. Testing Audit

### Conclusion

现有测试对旧口径覆盖较多，但对最新需求新增或强化点覆盖不足。最大缺口是 `rcsd_alignment_type` 在 `src/` 和 `tests/` 中没有实际字段断言，`ambiguous_rcsd_alignment` 阻断也没有闭环。

### Testing Gaps

- 五类 `rcsd_alignment_type` 未覆盖。
- 六类业务场景的截面边界只部分覆盖，fallback 未拆分 partial junction 与 road-only。
- SWSD/RCSD 负向掩膜覆盖不足，测试构造基本没有验证 unrelated SWSD/RCSD masks。
- complex unit/case bridge 有单连通和无洞测试，但缺少 negative mask、forbidden、terminal cut 下的桥接拒绝/裁剪断言。
- legacy `multi_semantic_rcsd_context` 测试不能替代新的 `ambiguous_rcsd_alignment` 阻断；前者表示窗口内存在无关 RCSD 语义对象并应进入负向掩膜，后者表示多个正向 RCSD 对齐候选无法唯一消歧。
- 30-case gate 已存在，39-case 统一 gate 未正式落地。

### Recommended Tests

- 新增 `test_step4_rcsd_alignment_type.py`，覆盖五类 alignment。
- 调整 `test_step4_surface_scenario_classification.py`，每个 scenario 同时断言 `rcsd_alignment_type`。
- 调整 `test_step5_surface_scenario_support_domain.py`，拆分 partial junction 与 road-only 截面边界。
- 新增 `test_step5_negative_masks.py` / `test_step6_negative_masks.py`。
- 扩展 `test_step6_surface_scenario_guards.py`，增加 inter-unit bridge 被 forbidden/negative mask 阻断。
- 新增统一 `test_anchor2_39case_surface_scenario_baseline_gate`。

## 5. QA Audit

### P0 Risks

- 最新 `rcsd_alignment_type` 需求未见实现闭环。
- 统一 39-case gate 尚未正式落地。

### P1 Risks

- CRS 与 valid geometry 有输出实现，但系统测试断言不足。
- 目视审计仍有人工签核缺口；PNG 存在不等价于视觉审计闭环。
- case-package 性能审计已有默认 39-case QA 阈值：`threshold_seconds_total = 240.0`、`threshold_avg_completed_case_seconds = 6.5`；该阈值用于发现明显退化，不替代 full-input 生产 SLO。

### Required Quality Gates

- `rcsd_alignment_type` 必须进入 Step4 JSON、Step5 输入、summary/audit。
- 原 30-case、新增 6-case、target11 与统一 39-case gate 全部通过。
- `accepted` surface 不得含 `no_surface_reference`。
- `rejected / runtime_failed / formal result missing` 写回 `fail4`。
- 所有发布 GPKG/GeoJSON 必须断言 CRS=`EPSG:3857`、geometry valid、非空、feature count 与 summary/audit 一致。
- Step6 guard 失败必须映射为 rejected，不能靠 cleanup 静默修复 topology。
- visual audit 必须产出 index 或等价索引，列出待人工确认项。
- perf audit 必须声明 39-case/full-input 的准出阈值。

## 6. Cross-Role Synthesis

五个角色的共同结论：

- 业务需求已经足够进入正式任务书。
- 正式编码的第一前置不是继续修个别 case，而是建立 `rcsd_alignment_type` 一等模型。
- Step5/6 必须从旧字段推断迁移到消费 Step4 frozen alignment object。
- negative mask 必须成为显式、可审计、多通道模型。
- complex/multi 必须有 unit-level 与 case-level 对齐证明。
- 39-case 统一 gate 是防止后续回归的必要门禁。
