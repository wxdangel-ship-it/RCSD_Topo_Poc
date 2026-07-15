# P02 武汉局部实验

本模块是武汉局部人工锚定 POC / 成果模块。模块复用 T08、T01、T05、T06，负责保存原始人工关系、在 Tool5 后转换 canonical target、组织实验运行证据与 QA，不替代任何正式业务模块。

## 当前状态

- 生命周期：`Active POC / 成果模块`。
- 上游：武汉局部 SWSD/RCSD 原始数据、用户人工关系。
- 下游：P02 实验报告与待补关系清单。
- 核心正式内网 Case 入口：`scripts/p02_run_wuhan_internal_case.py`；WSL 固定 Case 包装入口：`scripts/p02_run_wuhan_innernet_case.sh`。二者只负责本模块已确认的武汉单 Case 编排，不成为通用生产主链。

## 内网执行

输入目录必须包含：`node.geojson`、`road.geojson`、`RCSDNode.geojson`、`RCSDRoad.geojson`。

武汉内网机器在 WSL 仓库 `/mnt/d/Work/RCSD_Topo_Poc` 中直接执行，无需粘贴多行命令：

```bash
bash scripts/p02_run_wuhan_innernet_case.sh
```

该入口默认读取 `/mnt/d/TestData/数据整理/result/result/5524176501019109_5524182406597110`，使用仓库 `.venv/bin/python` 和已安装 PyQGIS 的 `/usr/bin/python3`，将控制台日志写入 `outputs/_work/p02_wuhan_local_experiment/<run_id>.console.log`。如需运行同格式的其它原始目录，可把目录作为唯一位置参数传入。

核心入口仍可单独调用：

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
