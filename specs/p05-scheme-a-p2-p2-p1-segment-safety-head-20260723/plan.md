# P05-Scheme-A-P2-P2-P1 实施计划

## 1. 数据流

```text
frozen P2-P1 dataset + OOF Run A/B + P2-P2-P0 lineage
  -> hash / denominator / Case-fold gate
  -> truth-free Segment candidate-set safety dataset
  + label-only carrier truth / Review / anomaly
  -> nested Case-grouped cross-fit safety head
  -> base proposal + accept / Segment fallback
  -> effective Segment carrier requirements
  -> Node conditional carrier closure
  -> RoadGraph materialization + hard gate
  -> deterministic replay + GO / NO-GO
```

## 2. 实现工件

- `scheme_a_p2_p2_p1_models.py`：内部 config 与 schema。
- `scheme_a_p2_p2_p1_dataset.py`：冻结输入、特征隔离与 Case-grouped 样本加载。
- `scheme_a_p2_p2_p1_network.py`：小型 candidate-set safety head。
- `scheme_a_p2_p2_p1_training.py`：嵌套 Case cross-fit、阈值选择和评分。
- `scheme_a_p2_p2_p1_oof.py`：正式 OOF、Segment fallback、Node closure、RoadGraph 与证据输出。
- 对应专项测试；不导出为正式 CLI/模块入口。

每个源码/测试文件写入前检查当前字节数；目标单文件低于 60 KiB，硬上限 100 KB。

## 3. 实施顺序

1. 冻结 SpecKit、manifest、门禁和输入 hash。
2. 准备 Python 3.10 + 项目已声明 `torch==2.9.1` 的可复现训练环境。
3. 实现 safety dataset，证明 truth/ID/坐标泄漏和 fold 重叠为零。
4. 实现小型 safety head 与训练折内阈值选择。
5. 运行 3 safety seed × 5 outer fold，生成完整 OOF safety score/decision。
6. 执行 Segment fallback、Node 条件化闭包和 51 Case RoadGraph 物化。
7. 正式双跑确定性、专项回归、体量/入口/资源审计。
8. 写入 validation summary；仅在结论稳定后同步 P05 项目级/模块级源事实。

## 4. 非目标

- 不重训、调参或改写 P2-P1 base scorer。
- 不新增 Road/Node candidate，不把 safety head 变成第二个 carrier 决策器。
- 不处理 Movement，不修改 T01-T12 或正式入口。
- 不使用业务规则事后修正错误 RoadGraph。
