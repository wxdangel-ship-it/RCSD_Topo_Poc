# T02 Stage3 语义成功与几何形态修复计划

## 1. 执行顺序

1. 先修 `706389`、`761318` 的业务语义成功条件
2. 保证 `520394575` 硬失败保护不被破坏
3. 做随机 10 例护栏回归
4. 再收 Stage3 最终 polygon 的几何形态
5. 跑全量本地 case-package visual 包

## 2. 第一阶段策略

- 梳理 `positive/negative rc groups`、`selected_rc_node_ids`、`polygon_support_rc_node_ids`
- 针对 `706389` 修复 `RC group semantic gap`
- 针对 `761318` 修复 T-mouth `selected node cover repair` 被 extra roads 打回的问题
- 保持 `foreign SWSD` 约束和 `outside_rc` 硬失败边界

## 3. 第二阶段策略

- 只在 `final polygon` 形态后处理层做最小改动
- 优先利用已有 regularize / fill-hole / seed-connected 逻辑
- 必要时增加更强的去孔洞、去无意义凹陷、去狭长桥接的局部规则
- 不通过放宽 acceptance 换取几何“看起来顺眼”

## 4. 审计方式

- 主线程负责实现
- 子线程 A：审计业务语义与 acceptance 护栏是否真实落地
- 子线程 B：审计几何后处理是否会误伤现有成功 case

## 5. 完成标准

- `706389`、`761318` 成功
- `520394575` 失败
- Stage3 单测全绿
- 随机 10 例护栏通过
- 本地全量 visual 包完成，供人工目视检查
