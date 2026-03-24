# T01 任务清单

## 本轮排工
- [x] 以 spec-kit 方式为 T01 数据格式迁移立项
- [x] 切出独立执行分支
- [x] 明确本轮只处理 I/O 格式迁移，不处理业务算法语义调整

## 批次 A：共享 I/O 层
- [x] 在 T01 共享 I/O 层增加 `GeoPackage(.gpkg)` 读取能力
- [x] 保留历史 `.gpkt` 兼容读取
- [x] 保留现有 `GeoJSON` / `Shapefile` 兼容读取
- [x] 增加同名输入优先解析规则：
  - `.gpkg`
  - `.gpkt`
  - 原始传入路径
- [x] 在共享 I/O 层提供统一的 `GeoPackage(.gpkg)` 写出能力

## 批次 B：阶段输出迁移
- [x] `step1_pair_poc` 官方矢量输出迁移为 `.gpkg`
- [x] `step2_segment_poc` / `step2_output_utils` 官方矢量输出迁移为 `.gpkg`
- [x] `s2_baseline_refresh` 官方矢量输出迁移为 `.gpkg`
- [x] `step4_residual_graph` 官方矢量输出迁移为 `.gpkg`
- [x] `step5_staged_residual_graph` 官方矢量输出迁移为 `.gpkg`
- [x] `step6_segment_aggregation` 官方矢量输出迁移为 `.gpkg`
- [x] `skill_v1` 官方输出中的 `nodes / roads / segment / inner_nodes / segment_error*` 迁移为 `.gpkg`

## 批次 C：裁剪数据双写
- [x] `slice_builder` 同时输出 `nodes.geojson` 与 `nodes.gpkg`
- [x] `slice_builder` 同时输出 `roads.geojson` 与 `roads.gpkg`
- [x] `slice_summary.json` 中补充双格式产物说明

## 批次 D：消费侧与辅助工具
- [x] `freeze_compare` 兼容消费 `.gpkg` 与历史 `.geojson`
- [x] `s2_baseline_refresh` 兼容读取 `.gpkg` 阶段产物
- [x] CLI 帮助文本改为 `GeoPackage(.gpkg)` 官方口径
- [x] 更新 T01 单元测试与 smoke tests

## 批次 E：正式文档迁移
- [x] 更新 `modules/t01_data_preprocess/architecture/overview.md`
- [x] 更新 `modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
- [x] 更新 `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- [x] 更新 `modules/t01_data_preprocess/README.md`
- [x] 在文档中明确：
  - 同名 `.gpkg` 优先读取
  - 历史 `.gpkt` 仅兼容读取
  - `slice_builder` 为唯一默认双写 `GeoJSON + GPKG` 的入口

## 非回退与验收
- [x] 每个实现批次完成后，运行相关单元测试
- [x] 每个实现批次完成后，验证 T01 CLI smoke 路径
- [x] 对 `PASS_LOCKED` 样例逐一验证最终 Segment 不回退：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS6`
  - `XXXS8`
- [x] 对 `FAIL_TARGET` 记录迁移前后差异快照：
  - `XXXS5`
  - `XXXS7`
- [x] 完成本地 `XXXS1-XXXS8` 的 `GeoJSON -> GPKG` 转换
- [x] 完成本地 `XXXS1-XXXS8` 的 `GeoJSON` 输入 vs `GPKG` 输入一致性比对
- [ ] 在样例未重新人工确认前，不更新 freeze baseline
