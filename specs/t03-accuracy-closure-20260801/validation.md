# Validation：T03 全量 Case 准确性闭环

> **状态说明（2026-08-02）**：本文件以下内容是 Scheme A 启动前的 `final_replay_v3`
> 历史验证记录，不再代表当前轮次最终验收。用户已撤销 QA 当前快照固定“4 正 16 负”并要求
> 重建 T12 真值；Scheme A 完成三套全量重放和 T12 独立证据审计后，必须追加新的最终结论。

## 1. 结论

本轮在独立分支 `codex/t03-accuracy-closure-20260801` 完成 T03 通用修复和三套真实数据重放。
49 条用户明确裁决（37 accepted、12 rejected）与最终 Step7 状态完全一致，误判数为 `0`；
生产代码不包含这些 Case ID。未修改正式入口、CLI 签名、T06 业务逻辑或输入 GPKG。

最终冻结输出为 `outputs/_work/t03_accuracy_closure_20260801/final_replay_v3`。

## 2. 冻结输入与基线

| 数据集 | Case 目录 | 有效执行 | 输入聚合 SHA-256 | 主干 accepted/rejected |
|---|---|---:|---|---:|
| QA T03_Error | `E:\TestData\POC_QA\T03_Error` | 54 | `9bfea7042a5b208522b137099bc1ed35d6da8a03393819074c58e8f3d71be765` | 17 / 37 |
| legacy T03 | `E:\TestData\POC_Data\T03` | 75（78 目录，按既有契约排除 3） | `82fc615de586de982832589edf29d18ca3302b93df0086518aa5ba0182abad60` | 71 / 4 |
| legacy T03_Error | `E:\TestData\POC_Data\T03_Error` | 258 | `d2ea4f174dbe390e52528c28a037c1576a7472a3128df0a14f849a16946a1d6b` | 186 / 72 |

基线 commit、本地 `HEAD` 与本地 `origin/main` 均为
`7c8b832edd229b807dc4478aa868a7e0ac19957c`。交付前再次执行 `git fetch origin main`
仍因 `Host key verification failed` 失败，因此远端是否在本轮期间前移不能在本机确认。

## 3. 最终结果

| 数据集 | total | accepted | rejected | missing | runtime failed | review PNG |
|---|---:|---:|---:|---:|---:|---:|
| QA T03_Error | 54 | 36 | 18 | 0 | 0 | 54 |
| legacy T03 | 75 | 73 | 2 | 0 | 0 | 75 |
| legacy T03_Error | 258 | 242 | 16 | 0 | 0 | 258 |
| 合计 | 387 | 351 | 36 | 0 | 0 | 387 |

351 个 accepted 中，机器视觉风险分层为 `V1=153`、`V2=198`。`V2` 表示业务硬门禁通过但仍有
边界/形态类人工观察信号，不等于 T03 失败；本轮不声称这 198 个面的视觉自然度已经由机器全部确认。

相对主干共发生 93 个状态变化：85 个 `rejected -> accepted`，8 个
`accepted -> rejected`。分数据集为：

- QA：27 个变化（23 放行、4 拒绝）；
- legacy T03：2 个变化（均放行）；
- legacy T03_Error：64 个变化（60 放行、4 拒绝）。

最终 v3 与审计字段补齐前的 v2 判定状态差异为 `0`。

## 4. 人工真值与残留拒绝

`tests/modules/t03_virtual_junction_anchor/data/t03_manual_truth_overrides_20260801.csv`
登记 49 条用户明确裁决。最终输出逐条比对：`mismatch_count=0`。

QA 18 条与 legacy T03_Error 16 条残留拒绝均已登记在 `case-audit.csv`，最终拒绝集合与台账
完全一致（missing=0、extra=0）。legacy T03 的 2 条拒绝为相同业务问题
`520394575 / 622700016`。主要根因包括：

- 原始 Direction topology 的 unmatched support component；
- compact alias 单侧 terminal collapse；
- connected semantic core 歧义；
- Class B support ownership 无法唯一证明；
- required RC carrier 未完整覆盖；
- 冻结合法空间内无法实现双节点 T 型桥接；
- 长跨度/跨层碎片、复杂非唯一锚定；
- 原始输入几何无效导致约束验证不可证明。

`12777955` 按用户意见继续保守拒绝并隔离为争议项，不登记为硬失败真值。

## 5. GIS 五项检查

### CRS

- 三套 Case 的距离、面积、buffer 和 topology gate 均在显式 `EPSG:3857` 中执行；
- QGIS 输出层 CRS 全部为 `EPSG:3857`；
- 本轮未对输入做隐式 CRS 猜测或回写。

### 拓扑一致性

- raw Road graph 严格消费 Road endpoint 与 `Direction 0/1/2/3`；
- mainNode/alias 只参与 canonical 分组和 portal，不产生零长度通路；
- `raw_topology_guard_audit` 明确输出 component、terminal、Direction 和 Road ID 证据；
- T12 只重验当前 raw Road/Node，不把 T03 rejected reason 直接发布为质量问题。

### 几何语义

QGIS `3.40.14`、GDAL `3.12.1`、PROJ `9.7.1`、GEOS `3.14.1` 对 351 个 accepted
surface 执行全量自动 overlay：

- 非空、有效、`EPSG:3857`、位于实现既有 `Step3 allowed_space + 0.6m` topology tolerance
  的硬门禁：351/351 通过；
- hard fail：0；execution error：0；
- 运行门禁最大数值外溢面积：`2.692113821707153e-06 m²`，低于 `0.0001 m²` 数值容差；
- 原始 allowed-space 覆盖率低于 0.90 的 5 个审计信号：QA `909265 / 1062256`、
  legacy T03 `513244637`、legacy T03_Error `500829840 / 507330743`；
- 原始 DriveZone 覆盖率低于 0.95 的 38 个记录继续保留为 audit-only，不用于推翻正确锚定。

上述双口径由 `validation/qgis_full_overlay_audit.py` 明确记录，未通过修改阈值隐藏风险。

### no-silent-fix 与审计追溯

- 输入源文件从未修改，所有 normalization 均为内存态并记录操作；
- 5 个实际采用 normalization 的 Case：`1617284 / 42544435 / 501668310 / 520855981 /
  602369732`，均为 Polygon 组件 `1 -> 1`、component delta `0`、area delta `0`、
  `source_modified=false`、`silent_fix=false`；
- 派生 regularization 遇到无效输入或无效结果时显式阻断，不再使用 `buffer(0)` 静默修复；
- 每个 Case 可由输入路径、Step3/4/6/7 JSON、GPKG、review PNG、运行根和数据指纹定位。

### 性能

- v3 三套全量重放：2026-08-02 01:13:58 至 01:29:45，wall time 约 15 分 47 秒，
  `workers=4`；前 6 分 24 秒与完整 T03 pytest 并行，因此该 wall time 只作为负载证据，
  不作为严格的主干性能对比；
- replay 进程最大采样 RSS 约 194 MiB；同实现上一冻结重放的 kernel `VmHWM` 为约 217 MiB；
- 未新增无索引全图扫描、依赖或正式执行入口。

## 6. 自动测试与治理

- T03：`283 passed in 384.44s`；
- T05 + T12：`160 passed, 2 warnings in 52.66s`；
- T06 的 T03/T05 消费回归：`61 passed in 12.48s`；
- targeted no-silent-fix/组件审计：`3 passed`；
- `compileall`：通过；`git diff --check`：通过；
- 修改/新增源码、脚本、测试 38 个，`>=100000 bytes` 为 0，`>=61440 bytes` 为 1；
- 最大文件 `step6_geometry_runner.py` 为 66268 bytes，已登记治理观察线；
- 生产代码 diff 对 41 个唯一人工真值 Case ID 扫描命中数为 0。

## 7. 可复核工件

- QA 结果与图片索引：`final_replay_v3/qa_t03_error_final/t03_review_index.csv`、
  `final_replay_v3/qa_t03_error_final/t03_review_flat/`；
- legacy T03 结果与图片索引：`final_replay_v3/legacy_t03_final/t03_review_index.csv`、
  `final_replay_v3/legacy_t03_final/t03_review_flat/`；
- legacy T03_Error 结果与图片索引：
  `final_replay_v3/legacy_t03_error_final/t03_review_index.csv`、
  `final_replay_v3/legacy_t03_error_final/t03_review_flat/`；
- QGIS 机器审计：`final_replay_v3/qgis_full_overlay_audit.json`；
- 残留失败台账：`case-audit.csv`；
- 完整测试日志：`outputs/_work/t03_accuracy_closure_20260801/pytest_t03_full_audit_v2.log`。

## 8. 待确认

1. 34 条 QA/legacy Error 残留拒绝已有通用原始数据理由，但其中标为
   `pending_visual_review` 的记录仍需用户最终目视确认；算法不会自动把它们登记为人工真值。
2. 5 个原始 allowed-space 覆盖率低于 0.90 的 accepted Case 通过正式运行门禁，仍建议结合本轮
   PNG 二次观察边界自然度；该信号不改变锚定状态。
3. 其余 `V2` accepted Case 也只表示业务正确但仍需目视确认边界自然度；本轮已生成全量 PNG，
   机器不会用视觉风险反写正式状态。
4. 本轮只验证本地可执行数据；未声称执行任何内网全量数据。
5. Git 远端因 SSH host key 无法刷新；本轮未提交、未合并、未推送。

## 9. Scheme A 当前快照重建最终验证（2026-08-02）

### 9.1 T03 三套全量重放

本轮从当前源码重新执行 Step3 与 Step4-Step7，不复用上一轮结果：

| 数据集 | 总数 | accepted | rejected | rejected Case |
|---|---:|---:|---:|---|
| QA T03_Error | 54 | 43 | 11 | `787617 / 823840 / 867264 / 950770 / 991243 / 994202 / 995764 / 1056150 / 1071119 / 522008569 / 522806716` |
| legacy T03 | 75 | 73 | 2 | `520394575 / 622700016` |
| legacy T03_Error | 258 | 242 | 16 | `867264 / 950770 / 991243 / 994202 / 1514722 / 1881692 / 12777955 / 53679574 / 74421922 / 507831701 / 520394575 / 520691911 / 522008569 / 522806716 / 620658564 / 622700016` |

结果根为 `outputs/_work/t03_accuracy_closure_20260801/scheme_a_replay_v1/`。运行从
`2026-08-02T00:06:33Z` 至 `2026-08-02T00:23:04Z`，wall time 约 `16m31s`；三套
`t03_review_index.csv` 均有完整 terminal result。

### 9.2 T12 当前 QA 真值

旧的跨快照“4 正 16 负”已撤销。当前 QA 输入聚合指纹为
`9bfea7042a5b208522b137099bc1ed35d6da8a03393819074c58e8f3d71be765`，对 11 个
T03 residual rejected Case 重新读取原始 SWSD/FRCSD Road、Node 与 Direction：

- `confirmed=1`：`522806716`，问题类型 `junction_required_topology_missing`；
- `excluded=9`：`787617 / 823840 / 867264 / 950770 / 991243 / 994202 / 995764 /
  1071119 / 522008569`；
- `source_excluded=1`：`1056150`，原因 `target_group_has_fewer_than_two_nodes`。

`522806716` 的缺失 movement 为 `528030913 -> 613908333`。输入臂已映射到
FRCSD Road `5885187979624401 / 5885187979624914`；输出臂映射到 Road
`5885187979624914`。该 Road `Direction=2`，在 inner node `5885187979624627` 只有 incoming
角色，没有 SWSD 所需 outgoing 角色。反方向 movement `613908313 -> 528030689` 可由
`5885187979624914 -> 5885187979624901` 的同一 raw portal 连通解释。

boundary Road 对应同时要求 `10m` target ownership、`10m` geometry retrieval 和 `25°`
outward heading。heading 从路口内端点向外采样 `10m`；该规则排除了“十字交叉处几何距离为 0，
却把垂直 Road 当作同一道路臂”的误匹配。全部决定已登记到
`tests/modules/t12_frcsd_quality_audit/data/t12_qa_junction_truth_20260802.csv`；生产代码不读取
CaseID。

### 9.3 GIS 五项门禁

- **CRS**：三套输入与 358 个 accepted surface 均显式以 `EPSG:3857` 处理；T12 参数写入
  manifest，混合 CRS 仍硬阻断，不做自动猜测。
- **拓扑一致性**：required movement 在 SWSD raw directed graph 派生，FRCSD 只在 raw identity
  endpoint directed graph跟踪；canonical alias 只可形成受限 portal，不创建通用零成本边。
- **几何语义**：QGIS `3.40.14-Bratislava` 对 358 个 accepted surface 全量检查，非空、有效、
  CRS 与正式 legal-space gate 为 `358/358`，invalid geometry 为 `0`。6 个 raw allowed-space
  ratio `<0.90` 的记录（QA `909265 / 952797 / 1062256`、legacy T03 `513244637`、legacy
  T03_Error `500829840 / 507330743`）保留为 audit-only，不反写业务状态。
- **审计追溯**：每条结果记录数据集、CaseID、输入/output GPKG、CRS、参数、Direction、Road/Node、
  heading、路径、排除/确认理由和 `silent_fix=false`。QGIS 报告为
  `outputs/_work/t03_accuracy_closure_20260801/scheme_a_qgis_overlay_audit.json`。
- **性能**：T03 三套全量重放约 `16m31s`；T03 测试 `476.22s`，T12 `24.78s`，T05/T06
  消费回归 `43.18s`，QGIS 358 面约 `26s`。均为当前本机实测，不外推为内网全量性能。

QGIS 与生产 GEOS 对 `0.6m` buffer 圆弧离散存在最大 `0.002508786m²` 的 engine-delta，已单独
记录但不覆盖生产 hard gate；生产同一 legal-space 计算的最大 escape 为
`2.69151373096009e-06m²`，低于 `0.0001m²` 明示数值容差。输入和输出几何均未被 QGIS 修改。

### 9.4 自动测试与治理

- 2026-08-02 提交前复核，T03：`307 passed in 457.76s`；
- 2026-08-02 提交前复核，T12：`93 passed, 2 warnings in 23.54s`；
- 2026-08-02 提交前复核，T05 与 T06 全量测试：`557 passed in 63.21s`；
- 2026-08-02 提交前复核，QGIS 3.40.14 对 358 个 accepted surface 的 hard gate 为
  `358/358`，执行错误为 `0`；
- `compileall`、`git diff --check`：通过；
- 本轮新增/修改代码/脚本/测试 `41` 个，`>=100000 bytes` 为 `0`，`>=61440 bytes` 为 `1`；
  最大 `step6_geometry_runner.py=72857 bytes`，已同步 code-size audit；
- 生产代码 diff 对本轮人工真值/审计目标 CaseID 扫描命中数为 `0`。

### 9.5 待确认

1. 本轮只执行本地三套 Case 数据与当前 QA 快照，未声称执行内网全量数据。
2. 6 个 raw allowed-space ratio 审计信号不影响当前业务状态；若需要改变视觉自然度口径，应另立
   任务，不得在本轮静默改判。
3. 用户已授权提交、推送并合并至主干；最终 commit 与远端 `main` 指针以本轮交付回报为准。
