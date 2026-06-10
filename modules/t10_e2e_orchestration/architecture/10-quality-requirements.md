# 10 Quality Requirements

## 1. CRS 与坐标变换

T10 v1 Case 空间切片 CRS 为 `EPSG:3857`。切片必须记录输入 CRS、CRS 来源、目标 CRS、中心点、半径与 bounds。

## 2. 拓扑一致性

T10 不执行 topology silent fix。空间切片不修复输入几何；invalid geometry、empty-after-clip、缺失 handoff、目录型 handoff 或后续拓扑不一致必须进入 audit。

空间切片必须对被选中道路补齐 `snodeid/enodeid` 端点节点，且保留道路完整几何。若端点补齐后仍存在缺失，必须在 `dependency_audit` 中记录 missing endpoint node count 与 node id。

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
- 每个外部输入 slot 的 source feature count、selected feature count、output path、output sha256 与 output bounds。

Case suggestions 必须记录 selector evidence 来源、匹配字段、匹配值和 row index。

## 5. 性能可验证

v1 记录 contract validation 计数、Case package 计数、slot 级 source / selected feature count 与 slice 文件大小。Case runner 必须记录每阶段耗时，T06 漏斗必须记录 Step1 / Step2 / Step3 的输入、候选、替换和输出规模。

文本 bundle 必须记录分片数量、分片文件名和 checksum，解包时校验后再恢复目录。
