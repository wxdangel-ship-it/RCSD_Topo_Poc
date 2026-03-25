# 11 风险与技术债

## 当前主要风险

- T02 已被登记为正式模块，但上游 T01 仍未在 repo 级生命周期中同步重分类，存在治理层级不完全对齐的风险。
- 当前 stage1、stage2、stage3 baseline 与文本支撑入口并存，若文档不及时收口，容易把正式契约、支撑工具和后续产线批处理方案混在一起。
- 当前实现使用轻量 GIS 栈，虽然足以支撑现阶段闭环，但在更大规模数据上可能需要更强的 IO / 空间索引插件支持。
- 共享大图层直连运行的 layer / CRS / 局部裁剪问题仍独立存在，不应被误判为算法回退。

## 当前可接受技术债

- `architecture/overview.md` 继续保留为概览入口，与标准 architecture 文档组并存。
- `specs/t02-junction-anchor/*` 与 `specs/t02-virtual-intersection-batch-poc/*` 仍保留在活动变更工件区，尚未归档。
- [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 已超过 `100 KB`，当前把输入读取、association、polygon-support、校验、render、bundle glue 聚在一个文件里。
- `node_component_conflict`、`no_valid_rc_connection` 等状态仍带启发式阈值，后续需要在更多样本上继续校验。

## 后续缓解方式

- 后续若继续推进 stage4 或正式产线级批处理，应先以新的变更工件和模块契约收口，再进入实现。
- 若引入新的 GIS / IO 插件栈，应同步补环境依赖说明与内外网安装方案。
- 后续优先拆分 `virtual_intersection_poc.py` 的 support 选择、状态校验、render 与 bundle glue，降低单文件演化压力。
- 若要支持共享大图层直连运行，应先补独立的数据接入基线和验收，不与当前锚定策略混验。
