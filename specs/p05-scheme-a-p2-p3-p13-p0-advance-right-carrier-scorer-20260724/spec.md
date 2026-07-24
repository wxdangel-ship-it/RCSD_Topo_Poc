# P05-Scheme-A-P2-P3-P13-P0 Spec

## 1. 目标

在P12R-R1冻结的`ADVANCE_RIGHT Segment`候选集合上训练object-conditioned
candidate-set scorer。模型逐Road给分并产生RCSD Road子集；低置信度、候选不可达、
access无效或安全约束不满足时回退到既有SWSD/Review，不修改冻结业务骨架。

本阶段回答：

> 在正确carrier已基本进入候选池后，神经网络能否在held-out Case上安全选择正确
> RCSD Road集合，并在不能判断时拒识？

## 2. 产品与业务范围

- 对象：P12R冻结的474个普通`ADVANCE_RIGHT Segment`。
- eligible：P12R的396个自动真值对象。
- hard fallback：40个T01 access无效对象和推理安全门失败对象。
- label-only安全评价：其余38个Review与8个R1 Oracle不可达对象；不得使用其名单
  作为推理硬规则，必须由模型空集合/拒识和通用安全门阻止错误RCSD发布。
- 输出语义：
  - 空集合：`KEEP_SWSD`；
  - 非空集合：候选RCSD Road子集，后续由确定性P12R语义层形成
    `RCSD_ONLY`或`MIXED_SPLICE`；
  - 模型不决定Movement，不新增/删除Segment，不修改Junction关系。
- fallback符合统一业务认知时计安全成功；自动选择错误Road集合计失败。

## 3. 数据角色

### 3.1 推理允许

- R1 truth-free candidate/object/evidence；
- 冻结T01 Segment/Road/Node；
- 原始RCSD Road/Node；
- 由上述数据产生的平移/旋转不变几何、拓扑和候选集合统计。

### 3.2 Label-only

- P12R truth；
- R1 candidate delta中的Oracle命中与truth component hit；
- T06 relation/final Road/Node；
- 人工裁决与历史Case权重。

label只能在candidate/feature signature冻结后读取。ID只允许Case内join和审计，
不得进入模型张量；原始绝对坐标、文件路径、Case名、fold、truth reason、
T05/T06终态字段不得进入特征。

## 4. 训练目标

- 每个candidate Road为二分类目标：是否属于该对象的条件化RCSD truth集合；
- object auxiliary head判断目标RCSD集合是否非空；
- decoder在fold-local阈值下输出候选子集；
- inner validation只用于early stopping、Road阈值和拒识阈值；
- held-out Case不得参与特征归一化、阈值、模型或checkpoint选择。

## 5. 模型与训练

- 模型：candidate encoder + permutation-invariant mean/max set pooling +
  object head + candidate decoder；
- 参数量目标：30万至150万；
- seeds：`17/29/43`；
- 外层：5个冻结Case fold；
- 每个外层fold选择其它一个fold为inner，其余为train；
- 优化器：AdamW，BCE多任务损失，deterministic CPU训练；
- 不继承P9 checkpoint，不读取Movement特征。

## 6. 验收门

### Gate 0 范围与lineage

- 474对象、6 Case、R1 candidate signature精确匹配；
- 3 seeds × 5 fold全部完成；
- 训练、inner、held-out Case零交集；
- T01–T12 modification=0。

### Gate 1 防泄漏

- feature freeze前label read=0；
- ID、绝对坐标、路径、Case/fold、T05/T06终态、Movement进入特征均为0；
- transform、normalization、阈值均只由train/inner产生。

### Gate 2 模型与选择能力

- 仅在R1 Oracle可达对象上评估raw exact-set；
- pooled raw exact-set accuracy `>=0.95`；
- 最差fold raw exact-set accuracy `>=0.90`；
- candidate binary macro-F1 `>=0.90`；
- object nonempty macro-F1 `>=0.90`。
- raw exact不得低于冻结5m Local Control。

### Gate 3 自动发布安全

- 每个seed、每个held-out fold accepted wrong=`0`；
- 78个Review的RCSD auto publish=`0`；
- 8个R1不可达对象的RCSD auto publish=`0`，且不得使用Oracle身份作推理mask；
- unsafe candidate、跨Case Road、非法Road/Node引用=`0`；
- 零错误前提下accepted coverage总体`>=0.50`，最差fold`>=0.30`；
- fallback后的terminal RoadGraph保持P12R硬门通过。

### Gate 4 确定性、GIS、资源

- 正式Run A/B内容签名一致；
- 6/6 Case CRS一致且为米制投影；
- geometry write/transform/silent fix=`0`；
- 参数量在30万至150万；
- 15个fold模型训练wall `<=900s`；
- peak RSS `<=4GiB`，无需GPU；
- 完整P05回归通过。

## 7. Decision

- `P05_SCHEME_A_P2_P3_P13_P0_MODEL_GO`
- `P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`
- `P05_SCHEME_A_P2_P3_P13_P0_SAFETY_NO_GO`
- `P05_SCHEME_A_P2_P3_P13_P0_AUDIT_NO_GO`

MODEL_GO只授权讨论将scorer接入P05方案A的提右soft decision层；不授权生产、
自动替换SWSD、修改T01–T12或解除确定性fallback。

## 8. 非目标

- 不补写T05提右锚定；
- 不修改P12R/P12R-R1历史工件；
- 不决定Movement；
- 不生成或修复geometry；
- 不新增CLI、script、`__main__.py`、Makefile或T10 stage；
- 不提交或推送Git。
