# P02 武汉内网 Case 执行入口验证报告

## 已修改

- 新增正式入口 `scripts/p02_run_wuhan_internal_case.py`，唯一必填参数为原始四 GeoJSON 所在 `--input-dir`。
- 新增正式 WSL 固定 Case 包装入口 `scripts/p02_run_wuhan_innernet_case.sh`；内网默认路径、仓库 `.venv/bin/python`、`/usr/bin/python3` PyQGIS、日志路径和 QGIS required 模式均已固化，不再要求在内网粘贴多行命令。
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
- WSL 包装入口 `bash -n`、`--help` 和 P02 自动化测试通过；包装入口文件体量 `6585 bytes`，低于 `100 KB` 硬阈值。
- WSL 包装入口完整回放目录：`outputs/_work/p02_wuhan_local_experiment/p02_wsl_wrapper_validation_20260715_091103`；使用仓库 `.venv/bin/python`、`/usr/bin/python3` 与 QGIS `3.22.4-Białowieża`，入口退出码 `0`，manifest `17/17` 阶段通过，49 项业务/GIS 硬校验通过，QGIS `56/56` 图层加载、相对数据源、工程写出/回读和预览渲染全部通过；控制台日志已持久化为同级 `p02_wsl_wrapper_validation_20260715_091103.console.log`。
- 合入 `main` 后从原始 GeoJSON 再次完整回放：`outputs/_work/p02_wuhan_local_experiment/p02_wuhan_main_e2e_20260714_2350`，17/17 阶段通过；49 项硬校验差异 `0`，13 个关键成果不一致数 `0`。
- T10 六案跨模块回归：固定 `T03=16 / T04=1 / T05=1`，`outputs/_work/t10_e2e_case_runs/t10_six_4b1c496_20260715_070100` 单次运行 `6/6 passed`、`60/60` 阶段通过，T06/P02/T10 自动化测试 `508 passed`。
- T10 GIS/拓扑检查：视觉汇总 `6/6 passed`；正式检查图层均为 `EPSG:3857`，缺失图层、端点缺路、advance-right 重叠异常均为 `0`；六案 RCSD Road 多 Segment 归属数均为 `0`，未执行 silent fix。
- T10 性能检查：六案 T06 Step1/2 + Step3 合计 `550.15s`，上一性能候选为 `551.07s`，比值 `0.9983`。

## 待确认

- T03/T04/T07 仍因输入缺少道路面、导流带和 `RCSDIntersection` 而不运行；执行链会明确登记，不伪造替代结果。
- 道路面覆盖率检查同样登记为 `not_run_unavailable`，待未来补齐面数据后再启用。
- 用户已确认内网 `/usr/bin/python3` 可导入 PyQGIS `3.22.4-Białowieża`，包装入口已固定使用该解释器；Agent 无内网访问能力，`/mnt/d/Work/RCSD_Topo_Poc` 与内网原始目录上的最终执行仍需由用户在 `git pull` 后启动。
