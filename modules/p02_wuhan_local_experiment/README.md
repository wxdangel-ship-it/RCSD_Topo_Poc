# P02 武汉局部实验

本模块是武汉局部人工锚定 POC / 成果模块。模块复用 T08、T01、T05、T06，负责保存原始人工关系、在 Tool5 后转换 canonical target、组织实验运行证据与 QA，不替代任何正式业务模块。

## 当前状态

- 生命周期：`Active POC / 成果模块`。
- 上游：武汉局部 SWSD/RCSD 原始数据、用户人工关系。
- 下游：P02 实验报告与待补关系清单。
- 正式内网 Case 入口：`scripts/p02_run_wuhan_internal_case.py`；只负责本模块已确认的武汉单 Case 编排，不成为通用生产主链。

## 内网执行

输入目录必须包含：`node.geojson`、`road.geojson`、`RCSDNode.geojson`、`RCSDRoad.geojson`。

```bash
.venv/bin/python scripts/p02_run_wuhan_internal_case.py \
  --input-dir /path/to/wuhan/raw
```

默认在 `outputs/_work/p02_wuhan_local_experiment/<run_id>/` 新建结果目录，执行 T08、T01、T05、T06，应用模块登记的 16 条人工关系、9 条端点修正和 `609020493` T 型人工修正，并生成 `14_qgis/p02_wuhan_local_analysis.qgz`。QGIS 运行时默认发现 `python-qgis-ltr` / `python-qgis`，也可用 `--qgis-python` 显式指定。

## 阅读顺序

1. `SPEC.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/02-data-and-domain-model.md`
4. `architecture/03-solution-strategy.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`
8. `INTERFACE_CONTRACT.md`
