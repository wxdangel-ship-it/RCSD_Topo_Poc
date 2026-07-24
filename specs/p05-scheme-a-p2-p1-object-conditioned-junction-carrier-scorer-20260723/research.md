# P05-Scheme-A-P2-P1 启动研究

## 1. 已确认事实

- Dataset-P0：741 sample、520 artifact、11,856 task target、51 Case、8,863 Segment。
- 可用 Segment=8,823，mask=40；`USE_RCSD`=2,190。
- 非T01 `USE_RCSD` Road、可用Segment Road、T06 final Road/Node对象可达率均为100%。
- PTO-P0候选共295,357个，51/51 Oracle semantic exact；候选不读取truth。
- 历史P1逐Segment模型能力高，但安全accepted coverage仅约0.35。
- 历史P2-P0只从单一T01/proposal Node图层生成40,334个Node option，受限bundle的`USE_RCSD retention=0.165753`。

## 2. 启动审计结论

`segment_inventory.csv.carrier_target` 与 `carrier_labels.jsonl.carrier_target` 不是同一阶段的状态：前者记录策略初始判断，后者应用Junction/Segment冲突和fallback后形成有效训练真值。两者同名但语义层级不同；P2-P1必须使用`carrier_labels.jsonl`作为Segment label，并保留策略状态仅作审计/禁止输入特征。

Dataset-P0 的100%对象可达性不能单独证明模型或JunctionUnit组合成功。本阶段必须先把PTO全量FINAL_NODE候选与Segment候选组成candidate-first联合数据集，并在训练前执行label-only compatibility Oracle；未达到100%则直接DATA_NO_GO，不允许靠训练或后处理掩盖。

## 3. 技术选择

- 保留P1已经验证的candidate/object/context交互形式，增加Node对象和JunctionUnit上下文；不继续扩大旧逐Segment模型容量。
- Segment candidate沿用已验证的P1候选分组；Node candidate改用PTO全量FINAL_NODE多来源候选，而不是单一proposal_nodes图层。
- 网络只输出score/confidence/uncertainty/anomaly；共享Node一致性、引用和拓扑属于通用图合法性约束。
- 训练和阈值全部fold-local；模型只在score完成后接触held-out label进行评价。

## 4. 资源预期

- 模型参数目标1M~5M，优先复用现有PyTorch可选环境。
- candidate/dataset构建主要为流式JSONL和有限GPKG读取，无需GPU。
- 正式3 seeds × 5-fold训练允许GPU，峰值VRAM不超过8GB；总训练不超过6h。
