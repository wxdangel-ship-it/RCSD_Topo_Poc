# Quickstart: 字段名归一化验证

## 目标

验证 `snodeid/enodeid/formway` 与 `snodeId/enodeId/formWay` 在 T03/T04 中逻辑等价，同时缺字段和冲突字段仍显式失败。

## 验证顺序

1. 运行共享字段解析单元测试。
2. 运行 T03/T04 大小写回归测试。
3. 运行受影响模块测试集。
4. 对 `997348` 与 `1026960` 的 FRCSD schema 执行读取 smoke。
5. 执行字段访问静态审计、源码体量审计和 git diff 审计。

## QA 检查

- CRS 转换结果与改动前一致。
- 道路端点邻接在 canonical/camelCase 输入下相同。
- 几何对象和原始属性未被字段查找器修改。
- 冲突信息包含 logical/original field names 和 feature 上下文。
- 性能微基准满足 spec 阈值。
