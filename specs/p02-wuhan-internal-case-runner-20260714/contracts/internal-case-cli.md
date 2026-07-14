# P02 内网 Case CLI 契约

## 正式调用

```bash
.venv/bin/python scripts/p02_run_wuhan_internal_case.py \
  --input-dir /path/to/wuhan/raw
```

## 输入目录

```text
node.geojson
road.geojson
RCSDNode.geojson
RCSDRoad.geojson
```

## 可选参数

- `--out-root`：run 目录父路径。
- `--run-id`：只能包含字母、数字、点、下划线和连字符；已存在则阻断。
- `--qgis-python`：显式 QGIS Python 入口。
- `--qgis-mode skip`：仅开发诊断；正式执行禁止。

## 成功输出

- `p02_run_manifest.json`
- `13_qa/p02_current_result_validation.json`
- `12_t06/<run-id>_t06/step3_segment_replacement/t06_frcsd_road.gpkg`
- `12_t06/<run-id>_t06/step3_segment_replacement/t06_frcsd_node.gpkg`
- `14_qgis/p02_wuhan_local_analysis.qgz`
- `14_qgis/p02_qgis_project_qa.json`

任一正式阶段失败返回非 0，并在 manifest 保留失败阶段和错误信息。
