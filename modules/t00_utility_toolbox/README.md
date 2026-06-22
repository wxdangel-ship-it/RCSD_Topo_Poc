# T00 Utility Toolbox

本文件是 T00 的模块阅读入口和文档索引。模块需求见 `SPEC.md`，架构设计见 `architecture/01~06`，稳定接口契约见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Support Retained。
- 当前主职责：保留历史一次性预处理、格式转换、数据归位和辅助检查工具。
- 上游：原始 Patch、A200 Road/Node、GeoJSON、MIF、JSON/NDJSON 等历史输入。
- 下游：人工排查、历史回归、T08 正式预处理能力迁移参考。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求，用业务语言说明 T00 为什么保留、解决什么支撑问题、什么算对。 |
| `architecture/01-introduction-and-goals.md` | 工具集合的上下文、目标、范围和非目标。 |
| `architecture/02-data-and-domain-model.md` | Patch、DriveZone、Intersection、DivStripZone、A200、GeoJSON、MIF、JSON 点位等输入对象语义。 |
| `architecture/03-solution-strategy.md` | Tool1-7、Tool9-11 的业务策略和落地方式。 |
| `architecture/04-evidence-and-audit.md` | summary、log、per-patch / per-file / per-record 审计分层。 |
| `architecture/05-quality-requirements.md` | CRS、覆盖、复跑、进度、格式转换和治理要求。 |
| `architecture/06-risks-and-technical-debt.md` | T00 与 T08 边界、历史工具债、CRS 和入口治理风险。 |
| `INTERFACE_CONTRACT.md` | Tool1-7、Tool9-11 的稳定输入、输出、入口和摘要契约。 |
| `history/` | 历史阶段材料，仅用于追溯。 |

## 3. 当前入口位置

T00 当前没有 repo 官方 CLI 子命令，官方执行入口是 repo root `scripts/` 下的固定脚本。

入口类别：

- `scripts/t00_tool1_patch_directory_bootstrap.py`
- `scripts/t00_tool2_drivezone_merge.py`
- `scripts/t00_tool3_intersection_merge.py`
- `scripts/t00_tool4_a200_patch_join.py`
- `scripts/t00_tool5_a200_kind_enrich.py`
- `scripts/t00_tool6_node_export.py`
- `scripts/t00_tool7_geojson_to_gpkg.py`
- `scripts/t00_tool9_divstripzone_merge.py`
- `scripts/t00_tool10_json_point_export.py`
- `scripts/t00_tool11_mif_to_vector.py`
- 模块内 callable：`run_patch_directory_bootstrap`、`run_drivezone_merge`、`run_intersection_merge`、`run_road_patch_join`、`run_road_kind_enrich`、`run_shapefile_geojson_export`、`run_geojson_to_gpkg_directory_export`、`run_divstripzone_merge`、`run_json_point_to_gpkg_export`、`run_mif_to_vector_export`

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/02-data-and-domain-model.md`
4. `architecture/03-solution-strategy.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`
8. `INTERFACE_CONTRACT.md`（仅在需要查具体工具输入、输出、状态和值域时）

## 5. 入口治理提示

T00 是历史支撑工具集合，不应继续扩展为新的业务生产模块。新增、删除、重命名或改变工具入口前，必须先获得入口治理任务授权，并同步 `docs/repository-metadata/entrypoint-registry.md`。
