# 实施计划

## specify

- 冻结五个人工裁决、真值优先级和集合真值语义；
- 冻结P9模型/输出，只允许评价层覆盖。

## plan

1. 校验P9 artifact manifest、正式decision与业务冻结边界；
2. 构建对象级人工裁决manifest和唯一join；
3. 对Control/Treatment逐seed计算合法性、优选、Clue与安全指标；
4. 生成裁决ledger、metrics、summary、manifest和验证报告；
5. 执行专项测试、五对象正式双跑和P05回归；
6. 同步P05模块源事实与P10验证结论。

## implement边界

- 新增P05内部只读callable与专项测试；
- 不修改P9模型/训练代码，不新增CLI、script或T10 stage；
- 不修改T01–T12，不提交或推送Git。

## 资源估算

- 训练/GPU：0；
- 只读取P9 evaluation/decision与summary，预计wall小于2分钟；
- 峰值RAM预计低于1GiB；
- 正式双跑预计小于5分钟。
