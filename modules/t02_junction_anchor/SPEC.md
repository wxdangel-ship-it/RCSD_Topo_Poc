# T02 模块规格：历史路口锚定模块

## 1. 模块定位

T02 是 Retired 历史模块，曾承载 SWSD 道路面资料判定、已有 RCSDIntersection 锚定、交叉 / T 型虚拟锚定、分歧 / 合流虚拟锚定和连续分歧 / 合流聚合等早期能力。当前主业务链已经将这些能力拆分给 T07、T03、T04 和 T08；T02 仅保留历史实现、历史入口、baseline 和证据包能力，用于追溯、回归比较和旧 case 复现。

## 2. 历史业务目标

- 判断双向 Segment 相关语义路口是否具备道路面资料。
- 判断有资料路口是否已经稳定锚定到 RCSDIntersection。
- 对有资料但未锚定的路口，构建早期虚拟路口面并输出审计材料。
- 对分歧 / 合流场景提供早期 Stage4 虚拟路口面能力。
- 为后续模块拆分沉淀可比较的历史 baseline 和证据包。

## 3. 历史范围

### 3.1 历史支持

- Stage1 `DriveZone / has_evd gate`。
- Stage2 `anchor recognition / anchor existence`。
- Stage3 `virtual intersection anchoring`。
- Stage4 `diverge / merge virtual polygon`。
- 连续分歧 / 合流复杂路口聚合离线工具。
- 单 / 多 `mainnodeid` 文本证据包。

### 3.2 当前非目标

- 不作为当前主业务链正式模块。
- 不承接新的路口锚定需求。
- 不替代 T07/T03/T04/T08 的当前职责。
- 不作为 T05/T06 当前正式 handoff 的来源。
- 不新增长期入口、字段规则或算法扩展。

## 4. 当前能力承接关系

| 历史 T02 能力 | 当前正式承接 |
|---|---|
| `has_evd` 与已有路口面 1:1 锚定 | T07 |
| 交叉 / T 型虚拟路口锚定 | T03 |
| 分歧 / 合流 / complex 虚拟路口锚定 | T04 |
| 数据预处理、类型修复、复杂路口预处理 | T08 |
| 后续 relation 融合 | T05 |

## 5. 历史输入

| 输入 | 用途 |
|---|---|
| T01 `segment / nodes` | 早期 stage1/stage2 的候选边界和 Segment 视角 summary。 |
| `DriveZone` | 判断路口是否有道路面资料。 |
| `RCSDIntersection` | 判断是否已有稳定 RCSDIntersection 锚定。 |
| `roads / RCSDRoad / RCSDNode` | Stage3/Stage4 虚拟面构造和局部 RC 关联。 |
| 文本证据包 | 单 case 复核和外部复现。 |

## 6. 历史输出

| 输出 | 用途 |
|---|---|
| `nodes.has_evd / nodes.is_anchor` | 历史锚定状态写回。 |
| `segment.has_evd` | 历史 Segment 视角统计。 |
| Stage3 虚拟路口面与审计 | 交叉 / T 型早期构面结果。 |
| Stage4 虚拟路口面与审计 | 分歧 / 合流早期构面结果。 |
| batch summary / audit / log | 历史运行解释、回归比较和问题追溯。 |

## 7. 历史业务步骤

| 步骤 | 业务说明 |
|---|---|
| Stage1 | 判断语义路口是否有可用道路面资料。 |
| Stage2 | 在有资料的路口中判断是否已经锚定到 RCSDIntersection。 |
| Stage3 | 对有资料但未锚定的交叉 / T 型路口构造早期虚拟路口面。 |
| Stage4 | 对分歧 / 合流候选构造早期虚拟路口面。 |
| 证据包 | 支持单 case 复核、文本回传和旧 baseline 复现。 |

## 8. 什么是对

- 使用 T02 文档解释历史行为、历史入口和历史 baseline。
- 新需求进入 T07/T03/T04/T08，而不是继续扩大 T02。
- 需要比较旧结果时，明确说明 T02 输出是历史参考，不是当前正式 handoff。

## 9. 什么是错

- 把 T02 表述为当前 Active 正式业务模块。
- 用 T02 输出替代当前 T07/T03/T04/T05 relation 成果。
- 在 T02 中新增当前主链所需的新规则。
- 把 Stage3/Stage4 历史状态直接解释为当前 T03/T04 发布状态。

## 10. 当前治理缺口

- 仓库入口登记仍需在后续入口治理中同步 retired / historical 口径。
- T02 历史长文档仍有大量旧运行说明，后续可在不改变入口事实的前提下继续压缩为追溯型文档。
