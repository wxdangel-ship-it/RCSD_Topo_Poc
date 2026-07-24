# P05-Scheme-A-P1 实施计划

## 1. 总体数据流

```text
truth-free registered replay + frozen business skeleton
  -> carrier candidate builder
  -> immutable candidate manifest/hash
  -> label-only join + grouped folds
  -> object-conditioned GraphSet scorer
  -> confidence/anomaly thresholds
  -> deterministic minimal-closure fallback
  -> RoadGraph materialization + hard gates
  -> 3 seeds x 5-fold OOF evaluation
```

## 2. 文件级设计

- `scheme_a_p1_models.py`：candidate/dataset/OOF 配置与稳定 schema。
- `scheme_a_p1_candidates.py`：truth-free replay 解析、Segment/Movement carrier candidate 构建与 candidate run。
- `scheme_a_p1_dataset.py`：候选冻结校验、label-only join、feature/泄漏审计与 grouped fold dataset。
- `scheme_a_p1_network.py`：candidate/context encoder、gated interaction、listwise 与 anomaly loss。
- `scheme_a_p1_training.py`：outer fold、inner validation、early stopping、阈值、checkpoint 与资源记录。
- `scheme_a_p1_execution.py`：score 选择、hard gate、最小闭包 fallback 与 RoadGraph 物化。
- `scheme_a_p1_oof.py`：三 seed OOF、非神经 baseline、指标、RoadGraph 和正式 run 汇总。
- `__init__.py`：导出 P05 callable；不新增执行入口。

每个文件保持单一职责；不向现有 `scheme_a_baseline.py` 追加训练逻辑。

## 3. Candidate 构建

1. 验证 Scheme A baseline manifest、PTO candidate manifest 与登记 strategy replay summary/hash。
2. 从 frozen skeleton 提取不含 carrier truth 的业务对象关系。
3. 从 T01 identity 与登记 strategy replay Road/Node/relation 建立候选 realization。
4. Road/Node ID 只用于 candidate payload/join；模型 feature 仅使用来源、枚举、局部计数、方向、拓扑和归一化几何统计。
5. candidate run 完成并哈希后，dataset builder 才读取 label。
6. exact reachability 非 100% 时停止，不用 truth 补候选。

## 4. 特征与模型

- object token：对象类型、Segment type、方向结构、Junction relation 角色、局部 degree/Movement 数量桶。
- candidate token：SWSD/strategy/fallback、Road/Node 数量桶、source/方向/端点闭包、局部 geometry shape bucket。
- context token：同组候选集合统计、相邻 Segment/JunctionUnit 统计与冲突证据状态。
- numeric：只使用局部平移/尺度归一后的长度、曲率、端点距离、覆盖和候选差异；不保留绝对坐标。
- 模型：token mean embedding + numeric encoder + object/candidate/context gated product/difference MLP；按 candidate group 输出 logits，另输出 anomaly logit。

## 5. 训练和阈值

- outer 5-fold 为正式 held-out；每个 outer train 内按稳定 business group 选择 inner validation。
- vocabulary、normalization、class weight、early stopping 和发布阈值只来自 outer train/inner validation。
- Segment/Movement 共用 encoder、分类型 calibration；weighted listwise CE 使用冻结 label weight。
- anomaly head 使用 RealityChangeClue/unsafe label-only target；hard structural conflicts 始终覆盖模型。
- 阈值先满足 `USE_RCSD precision>=0.95` 和 fallback recall，再最大化 accepted coverage。

## 6. RoadGraph 执行

- 只物化已选候选中声明的 Road/Node payload，不调用 T06 规则做事后修图。
- hard conflict 调用 Scheme A fallback resolver；Segment fallback 不向 Movement 传播，Movement 只因自身问题回退，且仅在其有效 carrier 确实共享或影响 Junction 内部拓扑时按 Junction 闭包升级。
- 每个 Case 输出 selected carrier、fallback audit、logical RoadGraph 与引用/CRS/方向/拓扑审计。
- duplicate ID 不同 payload、缺失 endpoint、CRS 冲突或非法几何直接失败并回退/阻断，不择近合并。
- 同 ID 跨来源 payload 仅在二维几何与 T01 核心字段精确一致时按 carrier 语义等价共存；保留原始已选 payload、逐 ID 审计且不合并属性，真实核心差异仍按 duplicate conflict 处理。
- 终态区分 `LEGAL/EXPECTED_FAIL/FAIL`；固定 manifest 中两个 SWSD baseline 非法 Case必须为 `EXPECTED_FAIL + clue + no publish`，其余49 Case必须合法，且两个 Case仍参加全部模型与异常指标。

## 7. 验证顺序

1. SpecKit/source-of-truth 一致性检查。
2. 单元、泄漏、破坏和 synthetic overfit 测试。
3. 51 Case candidate run 与 Gate 0。
4. 单 seed 5-fold development run，冻结超参数。
5. 3 seeds × 5-fold formal OOF。
6. 同 seed双跑、RoadGraph/GIS、资源和完整 P05 回归。
7. validation summary 与 GO/NO-GO source-of-truth 收口。

## 8. 非目标

- 不修改 T01–T12；不接 T10 或生产主链。
- 不训练自由 RoadGraph decoder。
- 不使用旧 PTO-A 改写骨架。
- 不新增 CLI、脚本、Makefile target 或其它长期入口。
- 不扩大到 `E:\TestData\POC_Data` 之外。
