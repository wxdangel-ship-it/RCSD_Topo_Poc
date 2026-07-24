# 实施计划

## 1. specify

- 冻结 T01 `ADVANCE_RIGHT access_valid=false` 为既有推理期硬安全资格。
- 冻结 P2-P3-P2 的模型、score、阈值、fold、seed 和 Dataset-P1 标签资格。
- 冻结残余 false-use 审计边界：只解释表征/模型能力，不创建业务强规则。

## 2. plan

1. 读取并校验 P2-P3-P2 manifest、Dataset-P1、方案 A baseline 和全部 hashes。
2. 将 6,275 eligible group 与冻结 Segment 清单精确 join，生成安全资格 ledger。
3. 对三 seed 原 decision 应用硬门，保持其余 decision 逐字段不变。
4. 与 2,588 context-only fallback 合并，复用通用 Junction/Node closure 和
   RoadGraph materializer。
5. 重算 accepted wrong、Review auto、context、expected-failure 和整图安全指标。
6. 加载当前 202 维推理证据与候选表达，按每个 seed/fold 的训练 Case执行
   exact-signature、标准化近邻和 candidate margin 审计。
7. 完成专项测试、完整 P05 回归、正式 Run A/B、体量/入口/GIS/资源审计。
8. 同步项目级和 P05 模块级源事实，形成阶段结论。

## 3. implement 边界

- 新增：
  - `scheme_a_p2_p3_p3_models.py`
  - `scheme_a_p2_p3_p3_audit.py`
  - 对应测试和模块导出
- 复用且不修改：
  - P2-P3-P2 模型、score、threshold 和正式工件；
  - Dataset-P1；
  - P2-P1 candidate、Node/Junction closure 和 RoadGraph materializer；
  - T01–T12 实现与接口。
- 不新增正式执行入口。

## 4. 验证

- 纯函数与身份/字段破坏测试；
- 新增测试及完整 P05 回归；
- 正式 Run A/B；
- 核心工件 hash 与规范化 signature 比较；
- CRS、geometry、骨架、入口、文件体量和资源审计。
