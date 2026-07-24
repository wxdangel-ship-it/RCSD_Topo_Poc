# Implementation Plan: P05 M1

## 1. 产品视角

M1 的产品结论是“可学习/不可学习”，不是“上线/替代 T06”。模型必须直接给出最终 Road 操作，最终指标按完整 T06 F-RCSD Road/Node 计算。固定 test 只有 5 个 Segment Case且不含标准 T10，因此结论必须同时展示固定 test、开发集 group CV 和标准 T10 shadow holdout。

## 2. 现状证据

冻结 M0 run 当前登记 51 个可用 RoadGraph Case，split 为 train `33`、validation `13`、test `5`。只读预审计得到：

- T01 Road + T05 RCSD Road 候选约形成 `21494 KEEP / 15130 DROP / 871 SPLIT parent` 的监督单元；
- SPLIT 子 Road 共 `1716`，子数分布为 1、2、3；
- 完整 truth 中 `14` 条 Road 无法回指候选父 Road，操作表示 micro coverage 超过 `99.9%`；
- M0 Case split 中存在少量相同 Road ID 跨 split，因此训练前必须建立实体泄漏门禁；
- 4 个 Segment Case 的目标 Segment relation 行缺失，但完整 Road/Node truth 有效，只能使用 `0.3` 上下文监督并记录 target-mask 异常。

以上数字在正式 M1 dataset run 中重新计算并写入审计，不能把本计划中的预审计数字当运行结果。

## 3. 架构视角

### 3.1 数据流

```text
frozen M0 manifest/samples/artifacts/split
                   |
                   +--> case run handoff --> t01_roads + hash
                   |
                   v
T01 Road + T05 RCSD Road/Node + T03/T04/T07 semantics
                   |
                   v
candidate Road graph + entity leakage guard
                   |
                   +--> deterministic baselines
                   |
                   +--> MLP baseline
                   |
                   v
RoadOperationGraphNet
  operation + source + direction + split geometry/endpoints
                   |
                   v
no-business-rule materializer --> Road/Node GPKG
                   |
                   v
M0 evaluate_frcsd + per-Case/CV report
```

### 3.2 特征

- 几何：固定点数折线采样、相对坐标、长度、弦长、曲折度、首尾方位和包围盒；所有距离在输入 CRS 中审计，禁止把 EPSG:4326 度数当米。
- Road 属性：`source/direction/formway/funcclass/roadclass/roadtype/layer` 等已存在字段按数值或受控类别编码；缺失值单独编码。
- Node/语义：候选端点是否能绑定 T03/T04/T07 node、`kind/grade/is_anchor/has_evd` 等原始字段及 T05 RCSD node 属性；模型特征使用不等于把字段固化为正式强规则。
- 图边：共享端点、有向可达和受限空间邻接；空间邻接阈值作为训练参数记录，不用于标签权重提升。
- 禁止特征：canonical Road/Node ID 数值、T06 relation status/reason、最终 Road ID、T06 generated/split reason、任何由 test truth 计算的统计。

### 3.3 模型

默认 `RoadOperationGraphNet`：

- polyline encoder：小型 PointNet/1D MLP；
- categorical/numeric encoder：MLP；
- 6 层稀疏 gated GraphSAGE/Graph Transformer block；
- hidden size `384`，FFN expansion `4`，dropout `0.1`；
- 输出 heads：operation、direction、source、split child count、最多两个有序切分比例/端点残差；
- 目标参数量约 `9M~11M`，运行时断言落在 `8M~15M`。

不依赖 `torch_geometric`；用 PyTorch 原生 `index_add/scatter_reduce` 完成稀疏邻域聚合。

### 3.4 物化边界

KEEP 复制输入几何但属性以模型输出为准；DROP 不输出；SPLIT 按模型预测的有序比例切分父线并生成新 Node/Road ID。物化器只验证比例、几何非空、端点引用与 ID 唯一性，失败时记录并阻断，不回退为 KEEP 或调用 T06 规则。

## 4. 研发视角

1. 新增 M1 config/schema、冻结 M0 读取器和输入 artifact 解析。
2. 构建 candidate/operation dataset、实体泄漏 mask、train-only normalization。
3. 实现 deterministic baseline、无图 MLP 和图模型。
4. 实现 checkpoint、推理、物化、不可变输出和环境审计。
5. 仅在 P05 `INTERFACE_CONTRACT` 暴露 Python callable；不修改 repo CLI。
6. PyTorch 作为 `p05-neural` optional dependency；本地训练使用隔离环境。

## 5. 测试视角

- 合成 fixture 覆盖 KEEP/DROP/SPLIT_1/2/3、缺父 Road、无效比例、端点缺失和 CRS 冲突。
- 数据集测试覆盖 M0 hash、approved exclusion、target/context 权重、四个 missing target relation、实体泄漏和 train-only normalization。
- 模型测试覆盖参数量、forward shape、加权 loss、固定 seed、checkpoint roundtrip 和无 test 参与调参。
- 物化测试覆盖 Road/Node 引用、重复 ID、方向、source、split geometry 和 no-silent-fix。

## 6. QA 视角

- 对全部 51 Case 重算候选、标签和 coverage；逐条列出 uncovered truth。
- 抽查 train/validation/test 跨实体与一跳邻域交集为零。
- 每个候选 run 记录 CRS、输入输出 hash、参数、环境、耗时、RAM/VRAM。
- 用 M0 evaluator 生成逐 Case GPKG 评价；hard failure 不能被平均指标掩盖。
- 最终固定 test 只运行一次；如门槛失败，保留失败证据并给出数据/表示/模型归因。

## 7. 依赖与入口

- 新 optional dependency：PyTorch CPU/CUDA wheel 由隔离环境安装，核心 `dependencies` 不改变。
- 新 callable：`build_m1_dataset`、`train_m1_model`、`evaluate_m1_run`；是否长期保留以模块契约为准。
- 不新增 repo CLI、T10 stage、root script 或内网入口。

## 8. 验证顺序

1. 文档/契约一致性与文件体量前置检查。
2. dataset fixture 和真实 51 Case dataset run。
3. 确定性基线与 MLP baseline。
4. 图模型开发集 group CV、消融和阈值冻结。
5. 标准 T10 shadow holdout。
6. 一次性固定 test 评估。
7. CRS、拓扑、几何、审计、性能与完整需求核对。

