# P05-JSG-PTO-P3 实施计划

## 1. 输入与边界冻结

验证 P1 candidate、P1 Oracle、P2 dataset、P0 truth、R2 truth 与 M0 fold 的 manifest/hash；不重跑 strategy proposal，不改变 51 Case 和排除项。

## 2. 实现分层

1. `jsg_p3_models.py`：dataset/OOF/training config、checkpoint 与稳定签名。
2. `jsg_p3_context.py`：从候选组与 dependency graph 构建 ID-free context token。
3. `jsg_p3_dataset.py`：验证冻结输入并生成 group context dataset/audit。
4. `jsg_p3_network.py`：candidate/context embedding、交互网络、listwise loss 与 ECE。
5. `jsg_p3_training.py`：outer fold、inner validation、seed、early stopping、checkpoint 和资源记录。
6. `jsg_p3_oof.py`：OOF score、PTO-A/PTO-B、RoadGraph/GIS 与正式 3-seed 汇总。
7. `jsg_p3.py` / package `__init__.py`：模块 Python callable；不新增正式入口。

## 3. 上下文设计

- Candidate：复用 P2 ID-free candidate feature token。
- Self-set：同组候选的 invariant/union token 与 option count。
- Dependency：P1 dependency group 的对象类型、invariant token 和数量桶。
- Reverse dependency：依赖当前 group 的对象类型、invariant token 和数量桶。
- Case profile：各对象类型 group 数量桶，只表达规模，不包含 Case ID。
- 禁止绝对坐标；如后续启用几何，只允许由冻结 evidence 推导的局部归一化量并先更新合同。

## 4. 训练协议

- outer 5-fold 只用于最终 held-out；每个 outer train 内按 business-ID 固定一个 inner validation 子集。
- fold-specific vocabulary、type/review class weight 和 normalization 只从 outer train 构建。
- group listwise cross-entropy；object type 平衡、Review/Unknown 安全权重在训练 fold 内计算并记录。
- 开发阶段先跑 candidate-only ablation 与单 seed N1；超参数冻结后执行 3 seeds × 5 folds。

## 5. 验证顺序

1. 单元、泄漏与合成 listwise 拟合测试。
2. 小规模真实 Case probe 与参数/资源审计。
3. 正式 context dataset。
4. 单 seed 5-fold 开发验收与误差定位。
5. 冻结超参数后执行 3 seeds × 5 folds。
6. 同 seed Run A/B、PTO/RoadGraph/GIS/资源/确定性审计。
7. 完整 P05 pytest、source-of-truth 完成态同步与代码体量审计。
