# 10 质量要求

## 正确性

- 语义路口必须基于 member node 集合。
- internal road 不进入 Arm。
- seed road 不得静默丢失。
- 每个 through 判断必须输出业务状态。
- 同一 Road 不应跨多个 Arm 重复占用，双向 Road 在同一 Arm 内承担双角色除外。

## 可审计性

- preflight 记录输入路径、CRS、字段、feature count、run id。
- case_input 保留原始三套路口 ID。
- arm_traces 记录 seed、路径、节点、decision、stop、issue。
- issue_report 记录异常与风险。

## GIS QA

- 输出 GPKG 使用输入 CRS。
- PNG 使用同一数据集 bounds；compare PNG 三栏使用同一视野范围。
- 不进行 silent geometry fix。

## 性能

- summary 记录总 group 数、dataset junction 数和运行耗时。
- synthetic 多组输入应在本地测试中稳定完成。

## 验证

- py_compile。
- 单元测试。
- synthetic single group。
- synthetic multi group。
- 输出结构、summary、review index、PNG、GPKG 检查。
- 禁止 Grade 源码扫描。
