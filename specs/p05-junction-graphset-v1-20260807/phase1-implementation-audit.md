# Phase 1：城市 Store 与完整 free-run 骨架审计

## 1. 当前输入合同

`CityEvidenceStore` 的输入不是某个 T07/T03/T04/T05 终态文件，而是按城市登记的原始
GIS 图层：

- SWSD Junction/Node/Road；
- DriveZone；
- RCSDIntersection、RCSD Node/Road；
- 道路面和导流带；
- 每类图层显式登记的 ID 字段、允许属性和定向业务依赖字段。

属性默认不进入 store。只有 `EvidenceLayerSpec.attribute_fields` 白名单字段可读，且
`label/truth/preferred/acceptable/selected/status/split/fold/family/route/T03/T04/T05`
终态命名字段会被阻断。

## 2. 城市 IO 与依赖切片

- 同一城市、同一不可变输入合同在一个进程内只解析一次；重复请求返回同一 store 对象。
- 每个 GIS layer 在唯一一次 Fiona 遍历中同时建立对象索引、依赖边和模型可见证据
  SHA-256，不再先做一次整文件 hash 再重复解析。
- 同一 city key 对应的路径、文件 size/mtime、字段合同、CRS 或依赖合同发生变化时直接
  阻断，不静默刷新。
- 空间窗口只生成初始候选；窗口外对象通过显式、定向业务依赖补全。
- 依赖不会自动反向传播，也不会沿整个 RCSD 路网做无界连通闭包。
- query slice 保存原 store 对象引用；不复制城市 Geometry/属性对象。

当前实现是单进程不可变内存 store。持久化 mmap 分片、城市级峰值内存和冷/热启动性能
尚未取得真实百万级城市证据，属于 T028 性能门，不把本轮单元测试解释为城市性能 GO。

## 3. GIS 与拓扑行为

- CRS 必须与登记 CRS 等价；不一致时阻断，不隐式重投影。
- 无 CRS、重复对象 ID、required dependency 缺失均为 hard failure。
- 非法几何保留原样并记入 manifest，不执行 `buffer(0)` 或其它 silent fix。
- 依赖关系按 `source -> target` 保存；空间命中与业务依赖分别进入审计字段。
- manifest 包含 layer、路径、CRS、对象数、非法/空几何数、证据 hash、依赖数和总
  fingerprint。

## 4. 完整输出骨架

`JunctionResultPrediction` 已具备：

- `step1_drivezone_state`；
- existing/virtual/no-valid/ambiguous/abstain surface plan；
- anchor state、完整 RCSD Node/Road 集合、唯一 main anchor；
- Node 等价类与 Road break fractions；
- planned/post-materialization topology signature；
- quality/review、分量置信度、完整方案置信度和 `abstain`。

`CandidateBinding` 先冻结当前 Junction 可见的对象和完整候选方案。预测只能原样选择
已绑定方案；修改锚定、增加对象、改变打断或用后续分数改写方案都会失败。

`JunctionEvidenceBatch` 使用 packed tensor：21D token 和 8D topology edge 按总 token
拼接，通过 offset 保留空集合和变长样本，不按固定 Case 数补齐。

## 5. 随机初始化 free-run

随机初始化骨架含 737 个参数，但 `safety_locked=true`，训练前只能输出
`ABSTAIN / UNTRAINED_MODEL`，不会因随机分数选择业务方案。

使用 development-only Oracle 工件 `row_results` 的 4,288 个身份键完成 identity-only
空证据合同审计：

| 指标 | 结果 |
|---|---:|
| identity | 4,288 |
| 合法 prediction | 4,288 |
| ABSTAIN | 4,288 |
| 非 ABSTAIN | 0 |
| 非法 prediction | 0 |
| blind-test access | 0 |

identity SHA-256：
`380251af9a1c9253ebc79b0b4806fb7202a7bed7e3c12ee723cedeeaf3fad32c`。

该结果只证明完整输出和安全回退链对全部开发身份可运行，不代表模型正确率、自动覆盖、
候选可达或城市 GIS 性能已经通过。

## 6. 源码体量

四个新增 Python 文件写入前均不存在，按 0 byte 检查。当前体量：

- `junction_graphset_v1_store.py`：25,577 bytes；
- `junction_graphset_v1_prediction.py`：27,609 bytes；
- `test_junction_graphset_v1_store.py`：9,218 bytes；
- `test_junction_graphset_v1_prediction.py`：7,292 bytes。

历史 60KiB 观察线文件保持只读；未新增正式 CLI、script、T10 stage 或模块公开接口。
