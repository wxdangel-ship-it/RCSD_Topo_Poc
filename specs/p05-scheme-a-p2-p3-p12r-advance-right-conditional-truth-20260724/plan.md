# 实施计划

## specify

- 以 `AdvanceRightRealizationUnit` 取代提右平面 carrier 标签；
- 冻结两侧普通 Segment 决策先行、提右两侧来源派生、mixed中间衔接及挂接
  Segment后处理；
- 冻结 T06 final为label-only、T01/原始RCSD为推理候选来源；
- 冻结硬安全门与候选召回决策阈值。

## plan

1. 校验 Scheme-A baseline、6个提右Case及全部T01/T06/原始RCSD工件；
2. 从冻结 access解析两侧普通 Segment，不读取T05；
3. 从T06 relation派生两侧 required source；
4. 从T01和原始RCSD构建 truth-free candidate components；
5. 从T06 final Road/Node、attachment/closure/topology audit重建realized source、
   splice和挂接Segment真值；
6. 建立确定性Case-grouped 5-fold；
7. 计算逐对象candidate oracle、fold召回和安全门；
8. 输出工件、专项测试、正式双跑和完整P05回归；
9. 同步P05模块级源事实与阶段结论。

## implement边界

- 只新增P05内部模块、模型、专项测试、P12R SpecKit和P05模块级文档同步；
- 不修改T01–T12正式实现或接口；
- 不修改P1–P11、旧P12实现和历史输出；
- 不新增正式执行入口；
- 不训练、不调阈值、不更新模型；
- 不提交或推送Git。

## 资源估算

- GPU/训练：0；
- 读取6个Case的T01、原始RCSD与T06最终工件；
- 预计wall time小于5分钟；
- 预计峰值RSS小于1 GiB；
- 输出只包含结构化审计，不复制大体量GPKG。
