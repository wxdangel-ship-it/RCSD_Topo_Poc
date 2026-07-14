# P02 武汉内网 Case 执行入口规格

**Feature Branch**: `codex/p02-wuhan-local-experiment-20260714`
**Created**: 2026-07-14
**Status**: Ready for implementation

## 1. 目标与边界

为 `p02_wuhan_local_experiment` 建立一个正式内网单 Case 入口。调用者只提供原始数据目录，目录内固定包含 `node.geojson / road.geojson / RCSDNode.geojson / RCSDRoad.geojson`。入口从原始数据执行到当前武汉 T06 结果，并生成可以直接打开的 QGIS 工程。

P02 只负责编排、人工事实消费、当前结果硬校验和证据收口；不把武汉规则扩展为通用生产规则，不接管 T08/T01/T05/T06 算法，不伪造 T03/T04/T07。

## 2. 用户场景

### US1 - 一参数内网复现（P1）

作为内网执行人，我只需要给出原始数据目录，即可获得新的独立 run root、完整日志、F-RCSD 和 QGIS 工程。

### US2 - 自动消费人工事实（P1）

入口必须自动消费模块登记的 16 条人工锚定关系、9 条端点修正，并在 Tool6 后、Tool4 前对 `609020493` 执行 `grade/grade_2=2` 的人工 T 型修正。

### US3 - 回退阻断（P1）

当前武汉结果的 Segment、T05 relation、T06 replacement、F-RCSD、Road 唯一归属或正式拓扑若发生回退，入口必须失败且保留可定位审计。

### US4 - QGIS 分析交付（P1）

入口必须将原始、T08、人工关系、T01、T05、T06 和 QA 图层打包到 QGIS 工程旁，使用相对 datasource，并执行工程回读校验。

## 3. 五类职责视角

### 产品

- 内网执行人只提供一个目录参数。
- 结果仍是武汉局部 POC，不提升为全量生产结论。

### 架构

- 唯一正式入口为 `scripts/p02_run_wuhan_internal_case.py`。
- 编排严格复用现有模块入口/callable；缺失 T03/T04/T07 显式 unavailable。
- QGIS 工程从已校验成果重新打包，不直接重写历史工程 datasource。

### 研发

- 将一次性端点修正、T 型人工修正和 QGIS 构建沉淀为 P02 内部 callable。
- run root 拒绝覆盖，逐阶段写 manifest、命令和日志。

### 测试

- 覆盖四文件输入契约、端点修正、T 型修正、空兼容工件、QGIS runtime 解析。
- 运行 P02 聚焦测试、T08/T01/T05/T06 回归和本地武汉原始数据全链路。

### QA

- 覆盖 CRS、拓扑、几何语义、审计可追溯性和性能。
- QGIS 校验工程写出/回读、图层数、feature count、XML、相对 datasource 和预览渲染。

## 4. 功能需求

- **FR-001**：唯一必填参数 MUST 是 `--input-dir`。
- **FR-002**：入口 MUST 逐字节复制四个 GeoJSON 到新 run root，MUST NOT 在原始目录写入或裁剪。
- **FR-003**：T08 顺序 MUST 为 Tool1→Tool3→Tool6→人工 T 型修正→Tool4→Tool5。
- **FR-004**：RCSDRoad copy-on-write MUST 只消费模块登记的 9 条端点白名单，并证明 Road 数量、ID 和几何不变。
- **FR-005**：人工关系 MUST 从模块登记的 16 条原始关系转换，MUST NOT 由调用者临时拼接。
- **FR-006**：入口 MUST 执行 T01、T05 Phase2、T06 Step1/2/3；Step3 不自动消费未显式授权的历史 group audit。
- **FR-007**：没有锚定关系的 Segment MUST 保留 SWSD。
- **FR-008**：普通 RCSD Road MUST 唯一分配到至多一个 Segment；特殊路口内部和 multi-Segment connectivity 可无普通 owner。
- **FR-009**：当前武汉结果硬校验失败时 MUST 返回非 0，且不得发布 `status=passed`。
- **FR-010**：默认 MUST 生成并回读 QGIS 工程；`--qgis-mode skip` 只属于开发诊断。
- **FR-011**：QGIS datasource MUST 使用 `14_qgis/data` 下相对路径，工程必须可随整个 `14_qgis` 目录移动。
- **FR-012**：新增入口 MUST 同步模块契约和 `entrypoint-registry.md`。

## 5. 成功标准

- **SC-001**：P02 单测及相关模块聚焦回归通过。
- **SC-002**：本地武汉原始数据从头运行得到 109 Segment、12 条 T05 relation、7 个替换、206 Road/243 Node F-RCSD、普通 Road 多归属 0、正式拓扑失败 0。
- **SC-003**：QGIS 工程图层全部有效，回读成功，datasource 文件全部存在且无绝对路径。
- **SC-004**：入口、内部源码和测试文件均低于 100KB；入口注册事实一致。
