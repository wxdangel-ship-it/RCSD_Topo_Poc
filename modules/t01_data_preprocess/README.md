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
- 最小输入：
  - `--road-path`
  - `--node-path`
  - `--strategy-config`（可重复，用于 `S1 / S2` 多策略运行）
- 默认无需显式传 `--out-root`
- 默认 `run_id` 规则：`t01_step1_pair_poc_YYYYMMDD_HHMMSS`
- 默认输出目录：`outputs/_work/t01_step1_pair_poc/<run_id>`
- 若需要覆盖默认规则：
  - 可显式传 `--run-id`
  - 或显式传 `--out-root`
- 当前输出：每个策略目录下生成 `seed_nodes`、`terminate_nodes`、`pair_nodes`、`pair_links`、`pair_support_roads`、`pair_table.csv`、`pair_summary.json`、审计 JSON
- 当前输出目标：便于在 QGIS 中叠加审查与做策略对比

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
