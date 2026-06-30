# T10 Segment 级证据包规格

**状态**：Implementation
**Scope Mode**：SpecKit implement
**Source Fact Status**：本文件是变更工件，不替代模块 source-of-truth。正式事实同步到 `modules/t10_e2e_orchestration/*`。

## 1. 背景

内网 Bug 分析经常以失败的 SWSD Segment 为入口。当前 T10 Case package 以 SWSD semantic junction id 作为 CaseID，只能围绕语义路口打包局部外部输入。对于 T06 中“有证据但最终替换失败”的 Segment，人工需要先从 T10/T06 端到端结果反查上下游证据，再手动组织可本地 replay 的轻量用例，效率低且容易遗漏必要输入。

本变更正式引入 Segment 级证据包：输入一个或多个 `SegmentID`，每个 Segment 独立生成一个轻量本地 T10 用例目录，并可继续使用 T10 Case runner 执行端到端 replay。

## 2. 产品视角

用户需要从失败 Segment 快速得到可移交、可解包、可本地执行的证据包：

- 一次输入多个 `SegmentID`。
- 输出必须按 Segment 拆分，每个 Segment 是一个独立轻量用例。
- 打包必须基于已有 T10 端到端执行结果反查 Segment 所需证据，避免只靠外部全量输入猜测范围。
- 每个 Segment 包必须保留证据链：Segment 来源、反查到的 T10/T06 run root、参与打包的外部输入、切片范围、被排除的模块间 handoff、QA 审计和文本 bundle。
- 打包后的目录必须能被 `scripts/t10_run_e2e_cases.sh` 执行，产出 T10 Case run manifest、T06 funnel、visual check 和 upstream feedback。

## 3. 架构视角

T10 的职责仍是编排、记录和组织证据，不修改 T01-T09 算法。

Segment package 在现有 Case package 之上扩展一个新的 scope 类型：

- 旧 `semantic_junction` Case：CaseID 仍为 SWSD semantic junction id。
- 新 `swsd_segment` Case：CaseID 为 `segment_<SegmentID>`，scope 记录 `swsd_segment_id`，并以 Segment 几何派生中心、bounds 和半径窗口。

Segment 打包必须从 T10 端到端 run root 中反查可用证据：

- 优先读取 run manifest / case summary 中的 T01 Segment、T06 Step2 problem registry、replacement plan、replaceable、Step3 relation 和 visual check 路径。
- 使用 T01 `segment.gpkg` 定位 Segment 几何和端点。
- 若 T06 problem registry / replacement plan / relation 中存在目标 Segment 行，manifest 必须记录对应 evidence rows 和来源路径。
- Segment package 仍只物化外部输入 slice；模块间中间产物进入 evidence reference / excluded handoff，不作为 package payload 复制。

## 4. 研发视角

本轮实现范围：

- 新增 T10 Segment scope 的空间切片 callable。
- 新增 Segment evidence package builder，支持单 Segment 和多 Segment。
- 新增正式脚本 `scripts/t10_pack_innernet_segments.sh`。
- 复用现有 text bundle 导出 / 解包能力。
- 保持 `scripts/t10_run_e2e_cases.sh` 兼容：runner 按 package manifest 读取 `external_inputs/<slot>/<slot>_slice.gpkg`，不关心 scope 是 semantic junction 还是 Segment。
- 同步 T10 `SPEC.md`、`INTERFACE_CONTRACT.md`、README、架构文档和入口 registry。

## 5. 测试视角

测试必须覆盖：

- 从 T01 `segment.gpkg` 按 `SegmentID` 定位 Segment 几何。
- 多 Segment 输入时输出 `cases/segment_<SegmentID>/` 独立目录。
- Segment package manifest 记录 `scope_type=swsd_segment`、`case_id_semantics=swsd_segment_package_case_id`、`swsd_segment_id`、center、bounds、source evidence。
- 切片保留道路完整几何和端点节点依赖，不裁断道路几何造成 replay 输入缺节点。
- text bundle 能导出并解包恢复多 Segment 目录结构。
- 脚本 shell 语法验证通过。

## 6. QA 视角

- **CRS 与坐标变换正确性**：所有可读 vector slot 在选择前归一到 `EPSG:3857`，manifest 记录 source CRS 和 output CRS。
- **拓扑一致性**：打包不做 geometry repair，不 silent fix；只记录 invalid geometry、空几何和端点依赖缺失。
- **几何语义可解释性**：Segment 窗口来自 T01 Segment 几何 bounds/centroid 加 `radius_m`，不是从局部样本反推字段语义。
- **审计可追溯性**：manifest 记录 T10 run root、T01 Segment source、T06 evidence path、目标 Segment evidence rows、输入 slot source/output/checksum。
- **性能可验证性**：summary 记录每个 Segment / slot 的 source count、selected count、materialized file count 和包大小。

## 7. 非目标

- 不改变 T01-T09 业务算法。
- 不把 T06 problem registry 直接变成替换白名单。
- 不改变旧 semantic junction CaseID 语义。
- 不把模块间中间产物复制进 package payload。
- 不执行或声明内网实际运行；本地验证只使用当前可访问的本地数据和已有 T10/T06 输出。
