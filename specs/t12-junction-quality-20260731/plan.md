# 实施计划

## 1. 影响面

- T12：新增 Junction 输入、规则、决定、输出和运行审计。
- T10：只增加 T03/T07 Step3 到 T12 的显式 handoff，不改变阶段业务关系。
- T07：只修正两处已授权的架构文字。
- T03、T05、T06、T09、T11：不修改算法或接口。

## 2. 实现分层

1. `junction_inputs.py`
   - 发现并校验 T03 正式 case 工件；
   - 读取 T07 `relation_cardinality_errors`；
   - 记录 run identity、文件指纹和完整性。
2. `junction_audit.py`
   - 建立原始 FRCSD support graph；
   - 重算 target projection、endpoint degree、component；
   - 执行 T03 两类准确率优先规则和排除规则；
   - 展开 T07 1:N/N:1 稳定错误。
3. `junction_outputs.py`
   - 写独立 Point CSV/GPKG 和 evidence GPKG；
   - 维护 Junction 计数守恒。
4. `runner.py / models.py / inputs.py`
   - 增加可选路径和独立阶段耗时；
   - 既有 Segment 主流程不变。
5. T10 Case/full runner
   - 传入 `t03_run_root`；
   - T07 Step3 存在时传入其 stage root；
   - 登记新增 Junction 输出。

## 3. 兼容策略

- 新参数均可选；不传时输出空但结构完整的 Junction 成果。
- 既有 Segment 文件名、字段、候选 ID、决定和计数不变。
- 新字段只进入 Junction 文件或 manifest/summary 的独立 `junction` 节点。
- T12 review CSV 继续只覆盖 Segment；Junction 本次全部为自动决定。

## 4. 性能策略

- FRCSD ID/endpoint/geometry 索引一次构建。
- 只对 T03 rejected candidate 的 support Road 建子图。
- SWSD Node lookup 与 Junction Point 几何一次构建。
- T07 仅线性读取与展开，不做二次空间匹配。
- summary 分别记录 `junction_input`、`junction_audit`、
  `junction_output` 耗时。

## 5. 验证顺序

1. 完成单元与契约测试，再实现最小代码。
2. 跑 T12 与 T10/T12 全量测试。
3. 使用本地 T03/T03_Error 数据回归 4 正 16 负。
4. 重跑 `1026960`，逐 ID/type 比较 Segment 基线。
5. 双跑稳定性、QGIS 工程、GIS 五项、体量和性能终检。
6. 生成参数化 T12-only 内网脚本并做 shell 语法检查。
