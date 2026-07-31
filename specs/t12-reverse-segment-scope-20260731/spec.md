# T12 非预期反向载体 Segment 范围收口

**Feature Branch**: `codex/t12-reverse-owner-exclusion-20260731`
**Created**: 2026-07-31
**Status**: Approved
**Input**: 用户确认反向 RCSD 的正式判定必须同时满足“位于明确路口锚定之间”和“未被其它 Segment 覆盖”，发现问题后先修复。

## 1. 业务目标

修复 T12 v7 把相邻或对向 Segment 的 RCSD Road 借入当前 Segment `50m`
局部图，并误报为当前 Segment `unexpected_reverse_carrier` 的问题。

正式确认必须同时证明：

1. 反向 raw FRCSD Road 路径从当前 Segment 一端唯一 T07 标准路口面出发，
   到另一端唯一 T07 标准路口面结束；
2. 路径端部 Road 与对应路口面存在实际接触或既有 `1m` 拓扑容差内接触；
3. 路口面之间的路径 Road 按既有 RCSD Road—Segment 唯一归属空间排序，
   唯一归属于当前 Segment；
4. 任一路径 Road 更符合其它 Segment，或当前与其它 Segment 归属不可唯一裁决，
   均不得自动确认当前 Segment 的反向错误；
5. 既有 SWSD 全图反向替代路径排除、双 T07 信用、raw 物理 Road、方向和几何门禁继续成立。

## 2. 五类职责视角

### 2.1 产品

- 最终错误区域继续按当前 SWSD Segment 输出。
- 候选中保留“锚点区间未证明”“其它 Segment 覆盖”“归属歧义”的根因。
- 准确率优先；无法证明唯一归属时自动排除，不扩大正式问题。

### 2.2 架构

- 只修改 T12 内部候选证据、自动决定和 additive 输出 schema。
- 复用 T12 已有 T07 标准路口面与 T06 已确认的 Segment 空间归属排序口径：
  `20m coverage > 50m coverage > geometry distance`。
- 不消费 T06 生成的 FRCSD ownership 作为目标真值；T12 仍直接审计原始 1V1 FRCSD。
- 不修改 T01–T11、T10 编排、CLI 或正式入口。

### 2.3 研发

- Segment 空间索引只构建一次；每个反向候选只查询实际路径 Road 的局部竞争 Segment。
- 路口面内几何从归属判定区间中剔除，避免共享路口内部几何制造跨 Segment 覆盖。
- 每条区间内 raw FRCSD Road 都必须获得当前 Segment 的唯一最优归属；并列不按 ID 猜测。
- 不硬编码 Case、Segment、Road 或 Node ID，不修改输入，不 silent fix。

### 2.4 测试

- 覆盖双 T07、双端 Road-surface 接触、当前 Segment 唯一归属的正式正例。
- 覆盖反向路径被其它 Segment 更强覆盖的误报回归。
- 覆盖端部 Road 未接触任一当前锚点面的误报回归。
- 覆盖归属并列时保守排除。
- 覆盖既有 SWSD 反向替代路径、弱锚点、必需方向缺失和输出契约回归。

### 2.5 QA

- CRS 必须是显式米制投影坐标系，所有距离在处理 CRS 中计算。
- raw Road endpoint 拓扑和 Road Direction 不变，不新增边、不吸附、不修复几何。
- manifest、CSV 与 GPKG 必须定位锚点间隔、逐 Road 归属、竞争 Segment 和决定规则。
- 同输入、参数、环境双跑的候选与最终结果内容稳定。
- 记录本地真实 Case 与内网全量性能；本地结果不替代内网全量结论。

## 3. 正式判定

### 3.1 锚点区间

- 仅双端唯一 T07 标准路口面可进入自动确认。
- 反向路径第一条 Road 到反向 source 标准面、最后一条 Road 到反向 target
  标准面的距离均不得超过既有 `1m` Road-surface 拓扑容差。
- 归属判定使用路径 Road 扣除两端标准面及 `1m` 容差后的区间内几何。
- 区间内没有实际 Road 几何时不得确认。

### 3.2 Segment 唯一归属

- 对每条区间内 Road 几何查询 `50m` 内 Segment。
- 依次比较 Road 在 Segment `20m` buffer 内覆盖率、`50m` buffer 内覆盖率和
  Road 到 Segment 的几何距离。
- 当前 Segment 必须是每条 Road 的唯一最优候选。
- 其它 Segment 更优时按 `unexpected_reverse_other_segment_covered` 排除。
- 最优证据并列、当前 Segment 缺失或证据不足时按
  `unexpected_reverse_segment_ownership_ambiguous` 排除。

### 3.3 自动确认

只有既有反向候选全部门禁、SWSD 无等价反向替代路径、双 T07 标准面、
锚点区间和当前 Segment 唯一归属全部通过，才允许：

- `issue_type=unexpected_reverse_carrier`
- `decision_rule=unexpected_reverse_raw_carrier_dual_t07_segment_scoped`

## 4. 输出与兼容

- T12 CLI、Python callable 和 T10 handoff 参数不变。
- 最终 confirmed GPKG 仍以当前 Segment 几何输出错误区域。
- 候选/确认/排除 CSV additive 增加锚点区间与 Segment 归属字段。
- carrier evidence GPKG additive 增加逐 raw RCSD Road 的区间归属证据层。
- schema 提升为 v8；既有字段不删除、不改名。

## 5. 范围

### In Scope

- T12 实现、测试、模块源事实、项目级 T12 源事实；
- 新 SpecKit 与真实 Case 回归；
- 代码体量台账和 GIS 五项 QA。

### Out of Scope

- 修改任何上游 Segment、Road、Node、Intersection 或 relation；
- 修改 T06 ownership 输出或把 T06 结果当作原始 1V1 FRCSD 真值；
- 修改 T10、CLI、脚本参数或入口登记；
- 自动修复、几何吸附、Case ID 特判。

## 6. 验收标准

1. 已知 v7 误报 `26219553_1026960` 不再正式确认，并保留其它 Segment
   覆盖及锚点间隔证据。
2. 双 T07、锚点间接触明确且唯一归属于当前 Segment 的合成正例仍正式确认。
3. 其它 Segment 覆盖和归属并列均稳定排除。
4. 原有两类必需方向缺失问题及 T10 调用契约不回归。
5. 入口参数不变，正式错误区域仍按 Segment 输出，内部保留根因。
6. 所有受影响源码/脚本低于 `100 KB`，完整内网性能列为独立待验项。
