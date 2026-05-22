# T08 Preprocess - AGENTS

## 开工前先读

- 先读 repo root `AGENTS.md`、`docs/doc-governance/README.md`、`SPEC.md` 与项目级 source-of-truth。
- 再读本模块 `INTERFACE_CONTRACT.md` 与 `architecture/*`。
- 本模块虽然以工具形式提供执行面，但工具属于项目正式数据链路组成部分。

## 当前范围

- Tool1：基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出均写回输入目录下同名文件。
- Tool2：Road 数据预处理，基于 GPKG 输入补充 `patch_id` 与原始 `kind`，最终输出 `EPSG:3857` GPKG。
- Tool3：Nodes 类型聚合，基于 GPKG Nodes/Roads 输入补充 `kind_2 / grade_2` 并处理环岛、复杂分歧 / 合流 mainnode，最终输出 `EPSG:3857` Nodes GPKG。
- Tool4：路口类型错误识别，基于 GPKG Nodes/Roads 输入校验 `kind_2=2048 / 4 / 16+8` 语义路口类型，输出 `nodes_error.gpkg`，不改写输入 Nodes/Roads。
- Tool4 只识别错误并输出审计，不执行自动修复。

## 允许改动范围

- `modules/t08_preprocess/**`
- `src/rcsd_topo_poc/modules/t08_preprocess/**`
- `tests/modules/t08_preprocess/**`
- `scripts/t08_tool1_vector_convert.py`
- `scripts/t08_tool2_road_preprocess.py`
- `scripts/t08_tool3_nodes_type_aggregation.py`
- `scripts/t08_tool4_junction_type_repair.py`
- 与 T08 登记、入口登记直接相关的项目级文档

## 禁做事项

- 不在模块根目录新增 `SKILL.md`。
- 不修改 T00 Tool4 / Tool5 契约。
- 不根据局部样本反推 Road / Node 字段语义。
- 不在 Tool4 中自动改写 `kind_2` 或重塑 Road/Node 拓扑。

## 必做验证

- 写入任何源码 / 脚本文件前，先记录当前文件字节数。
- T08 GIS 任务必须报告：
  - CRS 与坐标变换正确性；
  - 拓扑一致性，不允许 silent fix；
  - 几何语义可解释性；
  - 审计可追溯性；
  - 性能可验证性。
- 提交前至少执行定向测试、T08 相关脚本 `--help` 与 `git diff --check`。
