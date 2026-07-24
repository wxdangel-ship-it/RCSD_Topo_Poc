# 实施计划

## 1. specify

- 冻结 Dataset-P1 为 Segment 标签资格的前置合同。
- 冻结 context-only 的双重角色：上下文输入权重 0.3；监督标签贡献 0。
- 冻结 context-only 的安全整图实现为 `KEEP_SWSD`，之后才允许 Node/Junction
  真值闭包。
- 冻结历史工件只读保留和“本阶段不训练模型”的边界。

## 2. plan

1. 校验 Dataset-P1、Scheme-A baseline、P1/PTO candidate、历史 P2-P1、
   P2-P3-P2 和 P2-P3-P3 manifest/hash。
2. 将 8,863 个 Segment scope 与 baseline/candidate 精确 join。
3. 对 2,588 个 context-only Segment 应用唯一 `KEEP_SWSD` candidate，仅作为
   安全物化结果。
4. 运行 scope-first Node/Junction closure，记录初始冲突、闭包 Segment 和最终
   Node 真值。
5. 将新真值与历史 P2-P1 Segment label 比较，生成完整 delta 与残余对象重解释。
6. 使用既有 P2-P3-P3 decision/effective selection 和 P2-P3-P2 evaluation 重算
   seed/fold 指标，不训练、不调阈值、不重新物化 RoadGraph。
7. 完成专项测试、完整 P05 回归、正式 Run A/B 和资源/GIS/入口/体量审计。
8. 同步项目级和 P05 模块级源事实，保留旧结论并明确其已被 P4 重解释。

## 3. implement 边界

- 新增：
  - `scheme_a_p2_p3_p4_models.py`
  - `scheme_a_p2_p3_p4_scope.py`
  - `scheme_a_p2_p3_p4_audit.py`
  - 对应测试和模块导出
- 复用且不修改：
  - P2-P1 candidate feature/payload/compatibility edge；
  - P2-P3-P2 evaluation；
  - P2-P3-P3 decision/effective selection/RoadGraph；
  - T01–T12 实现与接口。
- 不新增正式执行入口。

## 4. 验证

- scope/候选/闭包纯函数测试；
- 新增专项测试及完整 P05 回归；
- 正式 Run A/B；
- manifest/hash、规范化 signature、对象 delta 和 exact residual identity 比较；
- CRS、geometry、骨架、入口、文件体量和资源审计。
