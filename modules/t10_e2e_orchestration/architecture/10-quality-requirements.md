# 10 Quality Requirements

## 1. CRS 与坐标变换

T10 v1 Case 范围声明 CRS 为 `EPSG:3857`。v1 不执行空间切片或坐标转换；后续一旦实现切片，必须记录输入 CRS、目标 CRS、转换参数和失败原因。

## 2. 拓扑一致性

T10 不执行 topology silent fix。缺失 handoff、目录型 handoff 或后续拓扑不一致必须进入 audit。

## 3. 几何语义

Case 范围必须由 SWSD 语义路口 ID 与半径表达，不得用任意运行目录或局部样本反推范围。

坐标只允许作为 SWSD 语义路口 ID 派生出的中心点信息，不得替代 CaseID。

## 4. 审计可追溯

workflow plan、handoff audit、summary 和 Case manifest 必须能定位：

- T10 v1 链路。
- T08 独立运行边界。
- 外部输入 slot。
- 模块间 handoff slot。
- Case scope。

Case suggestions 必须记录 selector evidence 来源、匹配字段、匹配值和 row index。

## 5. 性能可验证

v1 记录 contract validation 计数和 Case package 计数。后续接入真实执行后，必须记录模块级输入规模、输出规模和阶段耗时。

文本 bundle 必须记录分片数量、分片文件名和 checksum，解包时校验后再恢复目录。
