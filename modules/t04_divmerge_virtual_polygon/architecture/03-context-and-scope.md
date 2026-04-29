# 03 Context And Scope

## 1. 上下文边界

T04 处在基础道路 / 节点事实源与下游虚拟锚定成果之间：

- `t01_data_preprocess` 提供基础道路、节点和空间层事实源。
- `t02_junction_anchor` 提供历史 Stage4 业务经验；T04 不保留运行时代码依赖。
- `t03_virtual_junction_anchor` 提供 batch、review、summary 与 downstream node 输出模型的形式参考；T04 不复制 T03 业务语义，也不复用 T03 的 `fail3` 值域。

## 2. 输入范围

T04 当前有两类正式输入面：

- case-package：每个 case 自带 `manifest / size_report / drivezone / divstripzone / nodes / roads / rcsdroad / rcsdnode`。
- internal full-input：一次性加载 full-layer `nodes / roads / DriveZone / DivStripZone / RCSDRoad / RCSDNode`，由 T04 发现候选、收集 per-case 局部要素并直跑 Step1-7。

输入 CRS 以 `EPSG:3857` 为前提；任何坐标转换、裁剪、buffer、union、cleanup 都必须在审计材料中保留可解释路径。

## 3. 输出范围

T04 当前正式输出包括：

- case 级 Step1-7 status / audit / review / event-unit 工件。
- batch / full-input 级 `divmerge_virtual_anchor_surface*` surface 发布层。
- rejected layer、summary、audit layer、`step7_rejected_index.*`、`step7_consistency_report.json`。
- downstream `nodes.gpkg` 与 `nodes_anchor_update_audit.csv/json`。

`divmerge_virtual_anchor_surface.gpkg` 是正式几何真值；`nodes.gpkg` 是输入 node 层的 copy-on-write 状态回写副本，仅更新当前 selected / effective case 的 representative node。

## 4. 范围外事项

- full-input 候选发现不是 Step1 业务本体；Step1 只判断给定 representative candidate 是否进入 T04。
- Step4 的 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL` 是内部审计态，不进入 Step7 最终状态机。
- T04 不承担 roundabout、复杂渠化外的全局拓扑自动修复、学习型判定或跨模块统一成果模型。
