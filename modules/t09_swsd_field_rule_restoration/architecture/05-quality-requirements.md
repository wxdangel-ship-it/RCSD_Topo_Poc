# 05 质量要求

## 1. 业务正确性 Gate

- 默认调用必须是 `restriction_only_v1`；v2 只能显式启用。
- v2 优先级固定为 `Restriction > Laneinfo > special carrier`，confidence 不得反转优先级。
- Restriction Road-Pair 不折叠，未证明时不提升 Arm scope；不同 condition payload 不合并，完整与 partial 条件并存时 Movement 不得写成 fully prohibited。
- Laneinfo 只有方向匹配、序列完整、全部 code 可解释且 Movement 存在时形成确定 Road 级结论。
- `9`、`o`、未知码、不完整或方向不匹配必须是 unknown。
- special carrier 必须按 Arm 汇总，且只形成 `weak_derived`；`kind` 后缀不作为强规则。
- Road 级规则不得扩张为 Arm 级 restriction。
- 缺 RCSD Laneinfo 的 Laneinfo / special carrier 派生规则只进 candidates。
- 缺 allowed evidence 不等于 prohibited，缺 carrier 不得 silent fix。

## 2. GIS、拓扑与几何 Gate

### 2.1 CRS 与坐标变换

- 所有空间输入记录原始 CRS，并统一到 `target_epsg`，默认 `EPSG:3857`。
- 缺 CRS 或变换失败必须显式失败 / 跳过，不能套默认坐标解释；空间 JSON 的顶层 / feature CRS 必须完整且语义等价。
- summary 记录输入 CRS、目标 CRS 和转换状态。

### 2.2 拓扑一致性

- Movement 必须在真实 Arm / Road 拓扑中存在。
- Restriction scope promotion 必须覆盖经审计的等价 carrier universe。
- special carrier 分类必须能解释其 Arm 角色和核心路口关系。
- T06 relation、F-RCSD Road/Node、方向或 junction alias 缺失时不得生成 stable；relation source/status 必须满足严格白名单，Road 双端 Node 必须存在，方向必须是 `{0,1,2,3}` 中的有限整数。
- retained SWSD seed fallback 必须满足 Arm seed 和方向约束，并带风险标记。

### 2.3 几何语义

- Restriction geometry、Laneinfo geometry 和 F-RCSD restriction / candidate geometry 必须能回溯具体 Road carrier。
- Road 级规则的几何不能由整个 Arm carrier 笛卡尔积生成。
- 几何构造失败必须进入 skip / risk，不得 snap、补线或 silent fix。

## 3. 审计可追溯 Gate

每条结果必须能回溯：输入路径和 run、junction、Arm、Movement、Road / Road-Pair、原始 evidence、策略、priority、scope、condition、override、T06 relation、F-RCSD carrier、验证和跳过原因。stable 与 candidate 必须按 `source_rule_id` 原子互斥，重要问题不得只记日志。

## 4. 26 类测试场景

### 4.1 Restriction

1. Restriction 禁止、Laneinfo 支持：最终 prohibited，Restriction 获胜并记录冲突。
2. 同一 Restriction ID 多组 Road-Pair：每组独立保留。
3. 只覆盖部分 Road-Pair：不得无条件提升全 Arm。
4. 同条件下完整覆盖等价 carrier：可形成 `arm_to_arm`。
5. 分时 / 条件 Restriction：raw 条件不丢失，不变成普通全时禁止。

### 4.2 Laneinfo

6. 完整 Laneinfo 缺右转且存在右转 Movement：生成 Road 级右转排除。
7. 任一有效车道有右转箭头：Road 支持右转，不生成排除。
8. 缺左转且缺调头箭头：左转与调头均排除。
9. 缺左转但明确有调头箭头：左转排除，调头支持。
10. `9`、`o`、未知码或序列不完整：unknown，不生成确定禁止。
11. Laneinfo 与 Road 方向不匹配：不参与确定推理。

### 4.3 提前左转 / 提前右转

12. Arm 有提前右转、主路无右转箭头：形成位移 / 弱候选，特殊 Road 默认支持右转。
13. Arm 有提前右转、主路明确支持右转：主路仍支持，Laneinfo 覆盖弱推导。
14. 提前右转 Road 无其它方向箭头：其它方向只形成弱候选。
15. 提前右转 Road 明确支持直行：不得限制直行。
16. 提前左转对称场景同样覆盖。
17. 辅路提右、绕开核心路口提右、路口前提右：输出不同 carrier / displacement 状态；不能证明时复核。

### 4.4 优先级

18. 三类证据同时存在并冲突：Restriction 获胜，覆盖链完整。
19. 无 Restriction、Laneinfo 与 special carrier 冲突：Laneinfo 获胜。
20. 仅 special carrier：只形成弱推导，不伪装显式规则。

### 4.5 F-RCSD

21. Arm-to-Arm Restriction：生成 stable F-RCSD restriction。
22. Road 级 Laneinfo 规则：不得扩张为整个 Arm restriction。
23. 缺 RCSD Laneinfo：Road 级结果标记未验证并进入 candidates。
24. `replaced / retained_swsd / replaced+retained_swsd`：carrier 使用正确。
25. retained SWSD seed fallback：可回溯且有风险标记。
26. 缺 Relation、Road、Node 或方向不可解释：明确跳过并记录原因。

每个编号必须至少有一个直接断言对应其业务结果，不能只由宽泛端到端 smoke 间接覆盖。

## 5. 回归 Gate

- 全量现有 T09 测试通过。
- 默认 v1 与显式 v1 输出的兼容字段、规则 key、状态和 stable restriction 等价。
- v2 新字段在 GPKG / CSV / JSON 中一致，raw condition payload 可 round-trip。
- v2 的 stable / candidate 互斥，candidate 不被 stable 统计吸收。

## 6. T10 六 Case Gate

只读冻结基线：

```text
/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full
```

Case：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。

复用各 Case 相同 T01/T06/T08 handoff，在独立输出根运行默认 v1 与显式 v2。冻结参考是 T10 `6/6 passed`、T09 v1 合计 `8947` Arms、`29145` Movements、`31112` Evidence、`3265` restored rules、`4357` stable restrictions；验收时必须从冻结产物重新计算，不以文档数字替代证据。

v1 对比兼容字段、规则身份 / 状态和 stable key；v2 逐 Case与合计报告 DecisionStatus、RuleScope、priority、override、condition、stable、candidate / unverified、skip 和 elapsed time，并抽样回溯到原始 evidence 与 T06 carrier。

## 7. 性能 Gate

Restriction Road-Pair 索引、Road Laneinfo cache 和空间索引可以减少扫描范围，但不能改变证据身份或匹配审计。summary 必须记录各阶段输入量、输出量和耗时。六 Case 对比必须报告 v1/v2 耗时；出现数量级退化时不得在无解释、无定位证据的情况下 close。

## 8. QA 完成标准

CRS、拓扑、几何语义、审计追溯、性能五项必须分别给出通过证据或明确未通过原因。测试绿色不能替代真实六 Case 的 scope 扩张检查，文件存在也不能替代条件、override 和 candidate 内容检查。
