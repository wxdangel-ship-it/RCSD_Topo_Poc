# 06 风险与技术债

## 1. 业务风险

- 如果把 T05 relation 视为可直接替换 Segment，RCSD 数据裁剪、方向、短连接和路口内部结构差异会导致误替换。
- 如果把 buffer-only probe 或 repair candidates 当作白名单，会绕过 Step2 硬审计。
- 如果 Step3 在 `replaced+retained_swsd` 中未通过 `relation_status / frcsd_road_source_values / source_mix` 明确区分 RCSD 替换 carrier 与 retained SWSD carrier，T09 会误判真实替换道路来源。

## 2. 数据风险

- RCSD 原始方向可能不满足 SWSD dual/single 预期，需要 problem registry 回流方向性或 side-group 复核。
- T05 pair relation 可能缺失、同归一、错锚定或 1V多；T06 只能在受限高置信条件下当前 Segment 内重试。
- Surface evidence 可能来自 T04 reject、多候选或 Patch 冲突，不能作为 Step3 放行替换的捷径。

## 3. 结构债

T06 Step2 和 Step3 已形成较多诊断与后处理模块，包括 replacement plan、problem registry、advance right、detached carrier、endpoint closure、surface topology 和 topology connectivity。后续拆分应优先保持执行边界：Step2 决定 plan，Step3 执行 plan，QA 只审计结果。

## 4. 端到端修复后的治理缺口

近期 Case 修复提高替换成功率的方式是“分流问题并保留审计”，不是放松替换门槛。后续需要把 Step3 topology audit、surface topology audit、T10 visual check summary 和 problem registry 沉淀为稳定质量看板，支撑上游 T01/T03/T04/T05/T07 的迭代分工。
