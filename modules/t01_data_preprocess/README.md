# T01 数据预处理模块

> 本文件是 T01 的模块级摘要说明。长期源事实以模块文档与规格链为准；当前版本仍处于需求澄清期与文档初始化期。

## 1. 模块简介

- 模块名：`T01`
- 模块定位：数据预处理模块
- 当前用途：为后续“路段提取”与“路口类型重新赋值”需求澄清提供统一文档入口
- 当前说明：本目录当前是 T01 的文档草案位，不等于项目级生命周期已将其认定为正式 `Active` 模块

## 2. 已确认事实：当前阶段状态

- 当前状态：已进入 `Step1 Pair` 原型研发
- 当前产物：Step1 顶层 Pair 原型、策略对比输出与审查型结果
- 当前限制：当前只做 Step1 原型，不进入 Step2 / Step3 最终实现阶段

## 3. 已确认事实：当前优先能力

- 路段提取
- 路口类型重新赋值

## 4. 已确认事实：当前已确认输入

- `Road`
  - 图层含义：道路数据图层
  - 几何类型：`LineString`
  - 文件格式：`Shp` 或 `GeoJSON`
- `Node`
  - 图层含义：Node 数据图层
  - 几何类型：`Point`
  - 文件格式：`Shp` 或 `GeoJSON`
- 当前补充口径
  - `mainnodeid` 是语义路口聚合主依据；为空值、缺失、`0`、空字符串时，以当前 `Node.id` 为主
  - 若多个 Node 共享同一 `mainnodeid`，Step1 当前按一个语义路口处理；进入 / 退出这些 Node 的 `Road` 也按该语义路口统一并口
  - 复合路口组内只有 `id == mainnodeid` 的代表节点属性当前被视为有效属性来源
  - `direction` 中 `0` 与 `1` 当前都按双方向处理
  - 输入 CRS 统一归一化至 `3857`，字段统一做归一化处理
  - 当前异常处理口径为报异常，但不中断其它处理

## 5. 当前理解/归纳：文档索引

- 规格草案：`../../specs/t01-data-preprocess/spec.md`
- 文档阶段计划：`../../specs/t01-data-preprocess/plan.md`
- 文档阶段任务：`../../specs/t01-data-preprocess/tasks.md`
- 输入契约草案：`INTERFACE_CONTRACT.md`
- 高层说明：`architecture/overview.md`
- 启动记录：`history/000-bootstrap.md`

## 6. 已确认事实：运行与输出概览

- 当前入口：`python -m rcsd_topo_poc t01-step1-pair-poc`
- 当前切片入口：`python -m rcsd_topo_poc t01-build-validation-slices`
- 最小输入：
  - `--road-path`
  - `--node-path`
  - `--strategy-config`（可重复，用于 `S1 / S2` 多策略运行）
- 默认无需显式传 `--out-root`
- 默认 `run_id` 规则：`t01_step1_pair_poc_YYYYMMDD_HHMMSS`
- 默认输出目录：`outputs/_work/t01_step1_pair_poc/<run_id>`
- 默认执行辅助日志目录：`outputs/_work/t01_step1_pair_poc/<run_id>/logs`
- 默认切片输出目录：`outputs/_work/t01_validation_slices/<run_id>`
- 若需要覆盖默认规则：
  - 可显式传 `--run-id`
  - 或显式传 `--out-root`
- 当前输出：每个策略目录下生成 `seed_nodes`、`terminate_nodes`、`pair_nodes`、`pair_links`、`pair_support_roads`、`pair_table.csv`、`pair_summary.json`、审计 JSON
- 当前 Step1 输出口径补充：
  - `seed_nodes` / `terminate_nodes` / `pair_nodes` 当前按语义路口输出，不再直接按物理 Node 输出
  - 审查输出会补充 `representative_node_id`、`member_node_ids`、`member_node_count`
  - `pair_support_roads` 会同时保留物理端点与聚合后的语义端点字段，便于核对复合路口并口效果
- 当前输出目标：便于在 QGIS 中叠加审查与做策略对比
- 当前切片输出：默认按 `XXXS / XXS / XS / S / M` 生成多档 GeoJSON 切片，供后续 Step1 / Step2 分级验证
- 当前切片输出口径补充：
  - 切片当前按 `mainnodeid` 聚合后的语义路口做 core 选择，而不是按物理 Node 单独裁切
  - 切片输出仍保留物理 `roads.geojson` 与 `nodes.geojson`，以便后续 Step1 / Step2 复用
  - 默认 profile 已扩展为 `XXXS / XXS / XS / S / M`
- 当前切片执行建议：先单独跑 `XXXS` 做极小冒烟，再跑 `XXS`；若质量与覆盖仍不够，再继续 `XS / S / M`
- 当前性能口径补充：
  - Step1 已做一轮原型级性能优化
  - `search_audit.json` 当前采用“事件计数 + 样本事件”模式，而非全量搜索事件明细
  - `pair_summary.json` 当前会补充 `search_seed_count` 与 `through_seed_pruned_count`，用于解释实际搜索规模
  - 该口径用于降低大图运行时的内存与输出体量压力
- 当前内网执行口径补充：
  - 若内网仓库已存在且依赖已安装，后续默认只按当前分支执行下拉更新
  - 初始化命令仅保留给首次 clone 或环境重建场景

## 7. 待确认决策点

- 最终输出成果形式与最小属性集。
- 最终失败分级与审计记录方式。
- 路段提取边界规则。
- 路口类型重赋值规则与优先级。
- 上下游接口稳定假设。

## 8. 当前不纳入范围：当前不承诺内容

- 不承诺最终输出。
- 不承诺最终算法。
- 不承诺最终验收标准。
- Step1 当前输出不等于 Step2 / Step3 的最终结果。
