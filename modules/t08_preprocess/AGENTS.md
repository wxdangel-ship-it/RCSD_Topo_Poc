# T08 Preprocess - AGENTS

## 开工前先读

- 先读 repo root `AGENTS.md`、`docs/doc-governance/README.md`、`SPEC.md` 与项目级 source-of-truth。
- 再读本模块 `INTERFACE_CONTRACT.md` 与 `architecture/*`。
- 本模块虽然以工具形式提供执行面，但工具属于项目正式数据链路组成部分。

## 当前范围

- Tool1：基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出均写回输入目录并追加 `_tool1`。
- Tool2：Road 数据预处理，基于 GPKG 输入补充 `patch_id` 与原始 `kind`，并删除 `kind` 具有 `17` 主辅路出入口属性的 Road，最终输出 `EPSG:3857` GPKG。
- Tool3：Nodes 类型聚合，基于 GPKG Nodes/Roads 输入补充 `kind_2 / grade_2` 并处理环岛 mainnode，最终输出 `EPSG:3857` Nodes GPKG。
- Tool4：路口类型修复，基于 GPKG Nodes/Roads 输入校验 Nodes `kind_2=2048` T 型路口类型、`kind_2 in {8,16}` 一入一出分合流类型，并可消费 Tool6 人工确认成果，copy-on-write 输出完整 Nodes、可选 Roads 与 audit Nodes，不改写输入 Nodes/Roads。
- Tool5：复杂路口预处理，基于 GPKG Nodes/Roads 构建复杂分歧 / 合流路口，并可参考 T02 `node_error_2` 生成与修复逻辑从 `RCSDIntersection` 识别和处理错误 1 对多路口，最终 copy-on-write 输出 `EPSG:3857` Nodes/Roads/audit Nodes GPKG。
- Tool6：Nodes 类型质检，基于语义路口入出度、连续分歧合流 T 型候选与交叉路口候选规则输出人工质检 CSV 与 `node_error_tool6.gpkg`，不改写输入 Nodes/Roads。
- Tool7：交通限制显性化，基于 SW C 表 `CondType=1` 与 SW Road `inLinkID / outLinkID` 构建显性 restriction LineString，输出 `EPSG:3857` GPKG。
- Tool8：Laneinfo 箭头显性化，基于 SW Laneinfo `LinkID / Seq_Nm / Arrow_Dir / Lane_Dir` 与 SW Road `direction` 构建车道级显性 arrow LineString，输出 `EPSG:3857` GPKG。

## 允许改动范围

- `modules/t08_preprocess/**`
- `src/rcsd_topo_poc/modules/t08_preprocess/**`
- `tests/modules/t08_preprocess/**`
- `scripts/t08_tool1_vector_convert.py`
- `scripts/t08_tool2_road_preprocess.py`
- `scripts/t08_tool3_nodes_type_aggregation.py`
- `scripts/t08_tool4_junction_type_repair.py`
- `scripts/t08_tool5_complex_junction_preprocess.py`
- `scripts/t08_tool6_nodes_type_qc.py`
- `scripts/t08_tool7_traffic_restriction.py`
- `scripts/t08_tool8_lane_arrow.py`
- 与 T08 登记、入口登记直接相关的项目级文档

## 禁做事项

- 不在模块根目录新增 `SKILL.md`。
- 不修改 T00 Tool4 / Tool5 契约。
- 不根据局部样本反推 Road / Node 字段语义。
- 不在 Tool4 中做契约外拓扑重塑；Tool4 仅允许按契约修复路口类型，并在 Tool6 连续分合流确认修复时删除对应直连 Road。
- T08 成果输出文件名必须在扩展名前以 `_toolX` 结尾。

## 必做验证

- 写入任何源码 / 脚本文件前，先记录当前文件字节数。
- T08 GIS 任务必须报告：
  - CRS 与坐标变换正确性；
  - 拓扑一致性，不允许 silent fix；
  - 几何语义可解释性；
  - 审计可追溯性；
  - 性能可验证性。
- 提交前至少执行定向测试、T08 相关脚本 `--help` 与 `git diff --check`。
