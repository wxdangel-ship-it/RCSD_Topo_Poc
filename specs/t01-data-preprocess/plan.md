# T01 计划

## 当前阶段
- `spec-kit planning and implementation for GeoPackage I/O migration`
- `implementation completed`

## 当前目标
1. 为 T01 建立统一的 `GeoPackage` 输入/输出迁移计划。
2. 先收敛共享 I/O 层与文件命名策略，再逐步替换各阶段入口与输出。
3. 在迁移全过程中保持当前 accepted baseline 业务结果与样例审查口径稳定。

## 实施批次

### 批次 A：共享 I/O 层统一
- 在 T01 共享 I/O 层明确 `GeoPackage(.gpkg)`、历史 `.gpkt`、`GeoJSON`、`Shapefile` 的读取支持。
- 引入同名输入优先解析规则：
  - `.gpkg`
  - `.gpkt`
  - 调用方显式传入的原路径
- 在共享 I/O 层集中提供矢量写出能力，避免各脚本各写各的文件后缀策略。

### 批次 B：官方输出切换
- 将以下阶段/入口的官方矢量输出由 `.geojson` 切换为 `.gpkg`：
  - `Step1`
  - `Step2`
  - `Step4`
  - `Step5`
  - `Step6`
  - `Skill v1`
  - `S2 baseline refresh`
- CSV / JSON / Markdown 审计文件保持现状，不在本轮改格式。

### 批次 C：裁剪数据双写
- `slice_builder` 继续保留 `.geojson`，以便快速目视与轻量 diff。
- 同时新增同名 `.gpkg`，作为后续 T01/T02 级联与本地测试的正式矢量交付。

### 批次 D：消费侧与辅助工具对齐
- 更新 `freeze_compare`、`baseline refresh`、CLI 帮助文本、测试夹具与 smoke case。
- 保证新输出命名下，审计/非回退检查仍可跑通。

### 批次 E：正式文档迁移
- 在代码与测试稳定后，更新：
  - `modules/t01_data_preprocess/architecture/*`
  - `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
  - `modules/t01_data_preprocess/README.md`
- 正式把 T01 的官方输入/输出口径迁移到 `GeoPackage(.gpkg)`。

## 依赖与风险
- `fiona` 已在仓库依赖中可用，本轮不新增新的重型 GIS 运行时依赖。
- T01 现有 freeze/baseline 证据大量引用 `.geojson` 文件名；本轮不得批量重写历史证据，只能兼容消费。
- `slice_builder` 是唯一明确要求双写的入口，其他阶段若继续额外保留 `.geojson`，必须有明确审计理由，不默认扩散。
- 同名优先策略若散落在各模块实现，会放大维护成本；必须优先抽到共享 I/O 层。

## 回归策略
1. 每个实现批次完成后，先验证单元测试与 CLI smoke。
2. 再对 `PASS_LOCKED` 样例做最终 Segment 非回退检查。
3. 对 `FAIL_TARGET` 仅记录差异，不因格式迁移本身改写业务判定。
4. 在样例未重新人工确认前，不更新 freeze baseline。
5. 本轮实现已完成本地 `XXXS1-XXXS8` 的 `GeoJSON` 与 `GPKG` 输入一致性核对，最终 `segmentid -> road_ids` 对比无差异。

## 文档清理落点
- 过程文档：
  - `spec.md`
  - `plan.md`
  - `tasks.md`
- 实现完成后再同步正式文档：
  - `modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
  - `modules/t01_data_preprocess/architecture/overview.md`
  - `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
  - `modules/t01_data_preprocess/README.md`

## 边界
- 不新增执行入口脚本。
- 不顺手推进 T01 业务算法整改。
- 不自动刷新 freeze baseline。
- 不改写历史 baseline / freeze / history 目录中的旧文件名与旧证据路径。
