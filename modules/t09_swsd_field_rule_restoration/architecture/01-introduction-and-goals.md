# 01 引言与目标

## 1. 文档定位

本文件说明 T09 多证据规则恢复的架构背景、目标、兼容边界和非目标。模块需求以 `../SPEC.md` 为准，稳定接口以 `../INTERFACE_CONTRACT.md` 为准，详细方案见 `03-solution-strategy.md`。

## 2. 背景

SWSD 现场限制至少来自三类证据：Restriction 表达显式 Road-Pair 禁止，Laneinfo 表达进入 Road 的车道方向能力，提前左转 / 提前右转表达通行方向在 Arm 内的特殊承载或位移。三类证据的粒度、可靠性和信息损失不同，不能继续用单一 `rule_scope="movement"` 表达，也不能因局部证据命中就放大为整个 Arm 禁止。

T09 因此分两阶段工作：先在 SWSD 层恢复带 provenance、条件和 scope 的决策，再借助 T06 relation 把可证明的规则投影到 F-RCSD。当前数据缺少 RCSD Laneinfo，SWSD Road 级派生结果在 F-RCSD 上只能是未验证 candidate。

## 3. 目标

- 保持默认 `restriction_only_v1` 的既有调用与输出口径。
- 新增显式 `multi_evidence_v2`，固定执行 `Restriction > Laneinfo > 提前左转 / 提前右转`。
- 用统一 Decision、Evidence、RuleScope、condition 和 override 模型表达支持、禁止、未知、冲突、复核和未验证。
- 让 Restriction Road-Pair 只在安全证明后提升为 Arm-to-Arm。
- 让完整 Laneinfo 形成 Road 级支持 / 排除，并实现禁左与调头联动。
- 让 special carrier 按 Arm 汇总，只形成最低优先级弱推导。
- 让 Step3 区分 stable restriction 与 candidate，不放大 Road 级规则。
- 输出 GPKG / CSV / JSON 与 summary，服务 GIS、筛选、回放、T10 和人工复核。

## 4. 关键架构原则

1. **显式兼容**：策略只能由 callable 参数选择，不能由环境或数据静默切换。
2. **作用域守恒**：证据在哪个 Road / Road-Pair 成立，结论就先停留在哪个 scope；提升必须有独立证明。
3. **优先级确定性**：证据置信度不能反转 `Restriction > Laneinfo > special carrier`。
4. **未知保守**：缺失、不完整、方向不匹配或字段语义不明时输出 unknown，不补造事实。
5. **发布分层**：SWSD 已恢复不等于 F-RCSD 已验证，stable 与 candidate 必须物理分开。
6. **只读上游**：T09 不修改 T01、T06、T08、T10 或输入数据。

## 5. 非目标

- 不把 `multi_evidence_v2` 设为默认。
- 不生成 F-RCSD `RoadNextRoad`。
- 不以 F-RCSD 独立 Arm 构建取代 T06 relation。
- 不推断当前缺失的 RCSD Laneinfo、轨迹通行或未定义条件字段语义。
- 不根据 F-RCSD `source` 推断交通规则。
- 不新增 CLI、root script、Makefile 目标或模块主 runner。

## 6. 兼容边界

现有 callable 不传 `strategy_version` 时必须采用 `restriction_only_v1`。v1 继续只有 restriction 能改变禁行结论，现有 `ProhibitionStatus`、输出文件名和 stable restriction 兼容字段保留。v2 增加统一决策字段与 candidate 输出，但不能反向改变 v1。是否迁移默认策略需要独立需求、六 Case 验收和下游确认。
