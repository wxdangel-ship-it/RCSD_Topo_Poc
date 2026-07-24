# 实施计划

## specify

- 冻结P10后稳定Clue FP定义、Case级0.7与对象级1.0真值优先级；
- 冻结首轮人工目视清单的风险覆盖规则；
- 冻结零训练、零阈值调整、零geometry、零T01–T12修改边界。

## plan

1. 校验P9/P10/P8/Dataset-P1/Scheme-A baseline manifest、hash与正式门；
2. 对Control/Treatment应用P10对象级Clue覆盖并提取三seed稳定FP/FN；
3. 唯一连接Dataset-P1 scope、P8来源适用性与Scheme-A Segment inventory；
4. 为普通Segment生成T01 ID定位，为`ADVANCE_RIGHT`生成SWSD Road/access定位；
5. 生成50对象完整归因ledger和首轮人工目视CSV；
6. 输出metrics、summary、验证报告、manifest与确定性signature；
7. 完成专项测试、正式双跑、完整P05回归和文件体量审计；
8. 等待用户人工裁决后，再决定是否扩展审计或启动新的训练/校准阶段。

## 人工裁决收口追加计划

1. 校验19行填写完整性、枚举、preferred属于allowed及原始非填写列零漂移；
2. 生成带输入hash、业务前提和确定性signature的裁决接受工件；
3. 合并P10既有5对象，形成24对象级1.0真值快照；
4. 对冻结P9执行P10双跑，对新P10结果执行P11双跑；
5. 复算Clue确认误报、carrier合法性和剩余对象真值缺口；
6. 保持零训练、零阈值调整、零模型权重变化、零T01–T12修改。

## implement边界

- 只新增P05内部只读callable与专项测试；
- 不修改P9/P10/P8/Dataset-P1历史实现或工件；
- 不修改T01–T12，不新增CLI、script、T10 stage、`__main__.py`或Makefile target；
- 不提交或推送Git。

## 资源估算

- 训练/GPU：0；
- 只读取JSON/JSONL与QGIS工程存在性，预计wall低于2分钟；
- 峰值RAM预计低于1GiB；
- 正式双跑预计低于5分钟。
