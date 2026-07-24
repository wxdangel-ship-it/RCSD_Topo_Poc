# P05 方案 A Carrier 基线实施计划

## 1. 技术路线

新增与历史 JSG-PTO 隔离的 `scheme_a_*` Python callable。历史 P0–P3 文件、run 和指标保持只读；方案 A 不修改旧模型类，也不兼容性改写 `SegmentConnector` 为新真值。

数据流：

```text
M0 fold/weight + JSG-P0 lineage + T01 Segment/Road/Node + T06 relation truth
  -> Frozen Scheme-A Skeleton
  -> Strategy Baseline
  -> Segment/Movement carrier labels
  -> RealityChangeClue
  -> deterministic minimal-closure fallback
  -> immutable audit run
```

## 2. 文件级设计

- `scheme_a_models.py`：冻结骨架、carrier 标签、clue、fallback 与配置数据类。
- `scheme_a_baseline.py`：manifest/hash gate、T01/T06 解析、51 Case run 和不可变输出。
- `scheme_a_fallback.py`：纯函数 fallback resolver 与业务正确性判定。
- `__init__.py`：仅导出方案 A callable；不登记新入口。
- `tests/.../test_scheme_a_models.py`：canonical、骨架不可变和 enum 合同。
- `tests/.../test_scheme_a_fallback.py`：四级 fallback 与升级边界。
- `tests/.../test_scheme_a_baseline.py`：合成 manifest/hash/策略映射/提右/标签测试。

## 3. 数据和 lineage

正式 run 只接受：

- `p05_jsg_p0_20260721_04/_05` 中冻结 51 Case lineage；
- `p05_m0_20260721_06` 的 sample/fold/weight；
- lineage 指向的 `E:\TestData\POC_Data` Case 或已登记 P05 strategy replay/baseline；
- 明确排除 `T10-Error / 1213556_1263661`。

所有路径通过 config/manifest 传入，源码不硬编码 run ID 或 Case 清单。

## 4. 骨架构建

以 T01 Segment 为集合真值。旧 JSG 的 Junction、普通 Segment relation 和 PhysicalMovement 只作为冻结历史证据读取；所有 `advance_right` 从 T01 原样加入 Segment 集合。`pair_nodes/junc_nodes/roads` 不推断、不修复。方案 A canonical signature 不包含 wall time、绝对输出目录或模型分数。

## 5. Carrier 与 fallback

T06 relation 只提供当前策略基线和 label-only carrier 监督，不改变骨架。Movement carrier 从冻结 relation access leg 和共享 Node 证据构建；无法唯一证明时 mask 并输出 clue。

fallback resolver 不读取模型内部特征，只消费显式 failure/clue 与骨架依赖：Segment 局部、Junction 全闭包、Movement 独占或升级 Junction。输出只声明保留 SWSD/阻断发布，不直接修改 GPKG。

## 6. GIS 与质量验证

- CRS：T01 Segment/Road/Node、T06 relation、冻结 JSG 必须一致；不隐式重投影。
- 拓扑：Road 端点引用必须存在；不做吸附、补点或 silent fix。
- 几何：本阶段不改 geometry，只验证独立 Road 的存在与引用可发布性。
- 审计：输入、参数、环境、hash、Case/object/clue/fallback 可定位。
- 性能：逐 Case wall/CPU/RSS、P95/max 和总 CPU 记录。

## 7. 验证顺序

1. 单元测试和破坏测试；
2. 51 Case Run A；
3. 51 Case Run B；
4. 比较五类 signature；
5. 运行 P05 全量回归；
6. 汇总 validation summary，不把历史 P3 指标作为当前门禁。

## 8. 非目标

- 不训练网络；
- 不修改 T01–T12；
- 不新增 CLI/脚本/正式入口；
- 不提交、不推送；
- 不从局部样本反推新的上游字段语义。
