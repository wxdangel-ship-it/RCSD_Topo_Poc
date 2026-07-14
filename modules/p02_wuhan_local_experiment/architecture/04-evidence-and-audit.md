# 04 证据与审计

- Formal experiment evidence：converted manual CSV、T05 relation、T06 replacement plan、F-RCSD 和 topology audit。
- Source evidence：raw manual CSV、原始数据 hash、用户确认记录。
- Review-only：Tool6 candidate、T05 graph-unconsumable、T06 problem registry、待补关系。
- Compatibility：空 surface/evidence 文件必须标记 `unavailable_empty_compat`，不得作为模块成功证据。
- Input integrity：同时记录 Tool1 原始转换结果与 P02 工作副本的要素数、ID、缺失端点引用、CRS 和 hash；未经确认的缺失端点保持原样进入 T05/T06。
- Confirmed endpoint override：逐项记录 Road、字段、旧值、新值、用户确认来源、输入/输出 hash，以及要素数、ID、几何不变证据；当前只允许 `endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 登记的 9 项，禁止 `NodeLid/CrossLid` 和运行时几何推断。几何端点审计仅作为用户确认前的证据，用户授权后的显式清单才是执行输入。
- Replacement scope：逐个 Segment 记录正式 relation 是否齐全、是否进入 replacement plan；无锚定 Segment 必须保持未替换。
- Internal Case manifest：记录原始输入 hash、git commit/branch、Python 环境、逐阶段命令/耗时/日志、失败位置和最终产物路径。
- QGIS：独立 package manifest 记录复制到 `14_qgis/data` 的文件、hash 与相对路径；工程 QA 必须证明回读图层有效、无缺失 datasource、嵌入 QGS XML 可解析且 datasource 不含绝对路径。
