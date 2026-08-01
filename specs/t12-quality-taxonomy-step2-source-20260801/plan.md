# 实施计划

## 1. 技术上下文

- Python 3.10，GeoPandas/Shapely/Pandas，pytest。
- 正式入口保持 `scripts/t12_run_frcsd_quality_audit.py` 与 T10 现有 runner。
- 输出仍为 CSV/GeoPackage/JSON/Markdown。
- 性能重点是 Step2 全量 nodes/error GPKG 单次读取和线性分组。

## 2. Constitution Check

- 变更进入独立 worktree 和专用 SpecKit：PASS。
- 产品/架构/研发/测试/QA 五类视角齐全：PASS。
- 不新增入口；只扩展现有参数：PASS。
- 不修改 T07 算法或上游字段语义：PASS。
- GIS 五项、审计、性能均有验收门禁：PASS。
- 所有待修改源码/脚本写入前执行当前字节数检查：PASS，均小于 100 KB。

## 3. 实现分层

1. `issue_taxonomy.py`
   - 集中定义三组七类、中文语义、repair domain、旧值映射；
   - 映射 review/result status，校验 confirmed 完整性。
2. `junction_inputs.py`
   - 接受 `t07_run_root`；发现 Step2 root；
   - 加载 final nodes、error1/error2、summary/evidence；
   - 校验 final fail 集合与证据/summary，构建 fail2 conflict component；
   - 旧 Step3 参数只作定位兼容。
3. `junction_audit.py / junction_outputs.py`
   - J01/J02 改为新类型并补分类字段；
   - J03/J04 按 fail1/fail2 直接发布；
   - 输出 `result_status` 和统一字段。
4. `review_publish.py / outputs.py / models.py`
   - Segment 三类迁移，旧 review 输入兼容；
   - CSV/GPKG/summary 使用正式新类型；
   - schema 升级到 v10。
5. T12/T10 existing entrypoints
   - 新增 `--t07-run-root`；
   - T10 Case/full 传递已有 Step1/2 root，不再传 Step3 cardinality root；
   - T12-only 内网脚本改用 T07 run root，保持标准 T10 目录连续性。

## 4. 验证顺序

1. 先写 taxonomy 与 Step2 source contract tests，确认旧实现失败。
2. 实现最小代码并跑 T12/T10 定向测试。
3. 跑 T12 全量与 T10/T12 工作流。
4. 跑本地 `1026960`、T03 注册 Case 与两个误报 ID 检查。
5. 双跑稳定性、QGIS 工程、GIS 五项、性能、体量、compile、shell syntax、diff 终检。

## 5. 复杂度说明

不新建服务层或入口；新增 taxonomy 小模块是为消除 Segment/Junction 重复枚举和中文语义漂移。Step2 loader 保留在既有 `junction_inputs.py`，不引入跨模块抽象。
