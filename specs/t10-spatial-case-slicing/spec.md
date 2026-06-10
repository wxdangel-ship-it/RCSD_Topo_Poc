# T10 Case 空间切片证据包规格

**状态**：Implementation / spatial package fix
**Scope Mode**：SpecKit implement
**Source Fact Status**：本文件是变更工件，不替代模块 source-of-truth。正式事实同步到 `modules/t10_e2e_orchestration/*`。

## 1. 背景

T10 当前正式入口 `scripts/t10_pack_innernet_cases.sh` 支持按 SWSD 语义路口 ID 打包 Case 证据包，但 `INCLUDE_FILES=1` 的实现仍复制全量外部输入文件。多个 Case 下每个 `cases/<case_id>/` 都会携带完整 GPKG，导致 Case 包体量接近 `Case 数 * 全量输入大小`，不符合“以 SWSD 语义路口 ID + 周边半径为证据范围”的需求。

## 2. 产品视角

用户需要每个 Case 能独立查看，并且文件证据包只包含该 Case 半径范围内的外部输入。`shared_external_inputs/` 去重不是当前重点；真正需要修复的是 Case 目录内的文件不应是全量 GPKG，而应是局部空间切片。

## 3. 架构视角

T10 spatial package 仍不调用 T08、T01-T09 runner，不修改各模块算法。它只改变 Case 证据包物化策略：

- CaseID 仍为 SWSD semantic junction id。
- 从 `prepared_swsd_nodes` 中定位 Case member nodes。
- 由 member node geometry 派生中心点。
- 使用 `radius_m` 在 `EPSG:3857` 下构建 square window。
- 对 T10 外部输入 slot 逐个生成局部 slice GPKG。
- 模块间 handoff 仍只进入 manifest 排除清单，不进入 package payload。

## 4. 研发视角

本轮实现范围：

- 新增 T10 空间切片 callable。
- 修改 `build_case_evidence_package` 与 `build_multi_case_evidence_package`，使 `include_files=True` 默认写空间切片而非复制全量输入。
- 保留 `materialization_mode="copy_full"` 作为兼容和诊断能力，但正式脚本默认使用 `spatial_slice`。
- 更新正式脚本帮助文本和模块契约。

## 5. 测试视角

测试必须覆盖：

- 根据 SWSD `mainnodeid/id` 定位 Case。
- 半径窗口只输出窗口内 feature。
- 每个 Case 目录仍保持独立 `external_inputs/<slot>/`。
- manifest 记录 `selection_status=spatial_slice_completed`、center、bounds、feature_count、checksum。
- 拓扑不做 silent fix，只记录是否发现 invalid geometry。

## 6. QA 视角

- **CRS 与坐标变换正确性**：所有输入通过 vector IO 读入并归一到 `EPSG:3857`。
- **拓扑一致性**：不修补几何，不 silent fix；记录 invalid geometry 数量。
- **几何语义可解释性**：窗口来源为 SWSD semantic junction member node 几何中心与 `radius_m`。
- **审计可追溯性**：每个 slot 记录源路径、输出路径、source feature count、selected feature count、bounds、checksum。
- **性能可验证性**：summary 记录每个 Case / slot 的 selected count 与物化文件数量。

## 7. 非目标

- 不实现跨 Case 共享输入目录。
- 不执行 T01-T09 端到端 runner。
- 不按道路拓扑外扩窗口，不推断字段新语义。
- 不对输入数据做修复或拓扑清洗。
