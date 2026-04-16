# 计划

1. 从 `tests/modules/t02_junction_anchor/data/anchor61_manifest.json` 定位 `758888` 的官方 case-package，并复用现有单 case pipeline 运行当前实现。
2. 读取当前单 case `status.json / audit.json / output_files` 与原始 `nodes/roads/drivezone/rcsdroad/rcsdnode`，按 Stage3 审计字段重建 `Step1 ~ Step7` 中间图层。
3. 固定一个统一 bbox / north-up / scale，输出每一步对应的 `PNG / GPKG / markdown / json`，保证用户可逐张目视对比。
4. 运行 `test_anchor61_baseline.py`，确认诊断导出未改坏 baseline。
