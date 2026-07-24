# 实施计划

## specify

- 冻结P12R-R1目标、数据角色、candidate合同和验收门；
- Control为P12R 5m局部候选；
- Treatment只增加endpoint/JunctionUnit条件化原始RCSD候选；
- P12R truth仅在候选冻结后用于Oracle。

## plan

1. 验证P12R正式Run B与输入manifest；
2. 只读分析19个漏候选的原始RCSD endpoint incident carrier；
3. 冻结有向component/bundle、incident carrier、owner匹配和orientation规则；
4. 实现P05内部candidate builder与审计；
5. 复用P12R truth/fold计算Control/Treatment指标；
6. 输出逐候选证据、逐对象delta、fold、metrics、summary、manifest和报告；
7. 完成专项测试、正式双跑、完整P05回归和体量审计；
8. 同步P05模块级源事实。

## implement边界

- 只新增P05内部源码、测试、R1 SpecKit和P05模块文档；
- 后续candidate builder从P12R主审计拆出，避免主文件回填；
- 不修改T01–T12、P1–P12R历史实现或正式输出；
- 不新增CLI、script、`__main__.py`、Makefile或T10 stage；
- 不训练、不调模型阈值、不提交或推送Git。
