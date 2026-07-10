# 06 风险与技术债

## 1. 已知业务风险

- **作用域放大**：单 Road-Pair、Laneinfo Road 排除或 special carrier 若被放大为 Arm restriction，会制造错误禁行。缓解方式是 scope 守恒、安全提升审计和 stable / candidate 分层。
- **优先级丢失**：只输出最终结果会隐藏 Restriction、Laneinfo 与 special carrier 冲突。所有覆盖必须保留 `override_chain`。
- **未知当禁止**：Laneinfo 缺失、不完整、方向不匹配、`9`、`o` 或未知码不能形成强禁止。
- **条件扁平化**：不同条件 payload 合并或 Step3 硬编码 `CondType` 会把条件限制误成全时禁止。
- **兼容性漂移**：若 v2 被隐藏开启，T10 与既有消费者会在无版本证据时看到业务口径变化。默认必须保持 v1。

## 2. RCSD Laneinfo 缺口

当前实验数据没有 RCSD Laneinfo，因此只能证明 SWSD Laneinfo / special carrier 的 Road 级恢复，不能证明其在 RCSD 切分、合并或替换后的车道级等价性。这类结果必须标记 `unverified_due_to_missing_frcsd_laneinfo` 并进入 candidates。

该限制不影响 Restriction 已证明的 `arm_to_arm` stable 投影，也不影响能精确映射具体 from/to carrier 的 Restriction `road_to_road`。未来接入 RCSD Laneinfo 时应扩展 Verification 层，不推翻现有 Evidence / Decision / RuleScope 模型。

## 3. 条件字段语义债

T08 Tool7 可携带 `CondType` 与其它 properties，但当前模块源事实没有定义所有值的时间窗、日期、车辆或适用对象语义。本轮只保留 raw payload、condition identity 和 unknown 状态。

未来若正式启用具体条件字段，必须同步项目级约束和 T09 接口契约，说明可用语义、适用范围和未确认边界；不得根据六 Case 或单次样本反推并固化。

## 4. Restriction scope 证明债

现实 Restriction 可能是 Arm-to-Arm，但工艺只保留 Road-to-Road。完整 Road-Pair 覆盖是当前安全提升的必要证据之一，却未必能表达所有平行、切分和条件组合。无法证明的结果应保持 Road 级、suspected 或 manual review。

后续可引入更正式的 carrier equivalence 证据，但不得把“任一命中”作为快捷替代，也不得跨 condition identity 拼接覆盖。

## 5. Special carrier 分类风险

`formway & 128/256` 只证明提前右 / 左转候选，不单独证明辅路、绕开核心路口或路口前提右的拓扑类型。类型必须结合 Arm Road 角色和核心路口关系；不足时输出 unknown / manual review。历史 `kind` 后缀可留作 raw audit，但不再是强规则。

## 6. T06 handoff 风险

T06 relation 缺失、F-RCSD Road/Node 缺失、方向不可解释或混源 carrier 范围不清会阻断 Step3。`source=2` Road 只能在当前 Arm seed 范围消费；retained SWSD seed fallback 必须有方向和 junction alias 证明并带风险。

T09 不回写 T06，不通过 `source` 推断交通限制，也不通过几何 snap / 补线 silent fix 上游拓扑缺口。

## 7. 输出与消费者迁移风险

v2 新增统一决策字段和 `frcsd_restriction_candidates.*`。下游若仍只读兼容 `field_rule_status`，看不到 supported、unverified、scope 和 override；因此在 v2 成为默认前，T10 与其它消费者需要独立迁移验收。

stable 与 candidate 不能共用含糊文件名或统计分母。不同 condition identity 也不能被旧去重键折叠。

## 8. 性能与审计成本

按 Road 聚合 Laneinfo、按 condition identity 评估 Restriction carrier 覆盖以及输出 override chain 会增加内存和序列化成本。可以使用 Road-Pair 索引、Road cache 和空间索引优化，但不能牺牲 evidence identity、raw condition 或匹配可追溯性。六 Case 必须报告 v1/v2 耗时与计数。

## 9. 治理边界

T09 当前以模块 callable 为正式业务入口。Step3 text bundle 脚本只做证据提炼。后续若新增 CLI、root script、Makefile 目标或模块主 runner，必须先满足入口变更审计并同步 `entrypoint-registry.md`；本轮不新增入口。
