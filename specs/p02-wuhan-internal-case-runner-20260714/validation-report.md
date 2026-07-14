# P02 武汉内网 Case 执行入口验证报告

## 已修改

- 新增正式入口 `scripts/p02_run_wuhan_internal_case.py`，唯一必填参数为原始四 GeoJSON 所在 `--input-dir`。
- 新增 P02 端到端编排：Tool1→Tool3→Tool6→人工 T 型修正→Tool4→Tool5→人工关系转换→T01→T05→T06→硬校验→QGIS。
- 将 16 条原始人工锚定关系、9 条已确认 `SNodeId/ENodeId` 端点修正和 `609020493` T 型人工修正纳入可审计执行链。
- 新增当前武汉结果硬校验、运行 manifest、阶段日志、输入哈希、QGIS 数据包、相对路径工程和工程 QA。
- 同步 P02/T08/T01/T05/T06 契约、项目源事实、生命周期和入口登记。

## 已验证

- 最新正式单命令回放目录：`outputs/_work/p02_wuhan_local_experiment/p02_wuhan_e2e_required_20260714_2335`；使用 `qgis-mode=required` 和 QGIS 3.40.14，一次调用内 17 个阶段全部通过，run manifest 最终状态为 `passed`。
- 与前次结果 `p02_wuhan_internal_case_validation_20260714_v2` 对比：49 项业务硬校验逐项完全一致，差异数 `0`；5 个核心 T06 CSV 的规范内容完全一致；8 个关键矢量成果要素键和全部属性完全一致，几何在 `1e-8m` 容差内差异数 `0`，最大 Hausdorff 差异 `1.3969838619232178e-09m`，属于 Windows/WSL 坐标浮点序列化尾差。
- 当前结果硬校验：49 项全部通过。原始要素数 `143/163/655/469`；端点修正 `9` 项且修正后缺失端点为 `0`；人工关系 `16→12`、阻断 `0`；T01 Segment `109`；T05 RCSDRoad/RCSDNode `474/660`；T06 成功替换 `7`、F-RCSD Road/Node `206/243`、正式拓扑失败 `0`。
- 唯一归属：已使用 RCSD Road `62` 条，其中单 Segment `58`、特殊路口内部不归属 `3`、多 Segment 连通不归属 `1`、多归属 `0`。
- GIS：原始 CRS 为 `EPSG:4326`，处理结果为 `EPSG:3857`；抽查 11 个关键图层，无空或无效几何；未执行 silent fix。
- QGIS：正式单命令内完成工程生成；56 个图层全部加载、11 个分组齐全、工程写出和回读成功、嵌入 XML 可解析、缺失数据源 `0`、绝对 datasource `0`、预览渲染成功。
- 自动化回归：P02/T08/T05 `94 passed`，T06 `418 passed`，T01 `242 passed`，P02 修改后复核 `9 passed`；合计 `763 passed`。
- Python 编译检查和正式入口 `--help` 通过。

## 待确认

- T03/T04/T07 仍因输入缺少道路面、导流带和 `RCSDIntersection` 而不运行；执行链会明确登记，不伪造替代结果。
- 道路面覆盖率检查同样登记为 `not_run_unavailable`，待未来补齐面数据后再启用。
- 内网首次运行需要确认 QGIS LTR Python 可由 `python-qgis-ltr` / `python-qgis` 找到；若不在 `PATH`，通过 `--qgis-python` 或 `QGIS_PYTHON_BIN` 指定。
