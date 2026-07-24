# Research: P05 M0 数据与度量基准

## 决策 1：P05 Road 目标

- **Decision**: 最终 Road 语义固定为 T06 Step3 F-RCSD Road/Node。
- **Rationale**: 用户已明确选择该语义；52 Case baseline 提供可追溯 T06 handoff。
- **Rejected**: 混用其它 RoadGraph POC 的 support state 或 Patch Vector 高精语义。

## 决策 2：数据范围

- **Decision**: Case 输入只接受 `E:\TestData\POC_Data` 下七个登记根；baseline 仅作为这些输入的标签 lineage。
- **Rationale**: 用户显式限定本次实验范围。
- **Rejected**: 自动吸收 `POC_QA`、D 盘内网或 outputs 中无法回指当前范围的样本。

## 决策 3：标签强度

- **Decision**: T03/T04 目标对象 `1.0`；T10 Case `0.7`；T10 Segment 目标 `0.7`、上下文 `0.3`。
- **Rationale**: 直接落实用户人工检查边界。
- **Rejected**: 将目录内所有对象提升为同等人工真值。

## 决策 4：T03/T04 几何标签缺失

- **Decision**: 单点 Case 可提供强对象/场景标签；surface/relation artifact 缺失时对应 task masked。
- **Rationale**: Case 目录主要包含输入，不能从“人工检查过”推断不存在的 polygon/relation 文件。
- **Rejected**: 运行规则后无审计地把新输出冒充历史人工修正真值。

## 决策 5：canonical T10 标签

- **Decision**: 由 baseline summary 与每个 `t10_e2e_case_run_summary.json` 的 handoff 解析，不硬编码 Case 输出相对路径；manifest 中 WSL 路径使用既有 runtime path normalization。
- **Rationale**: 六案与 52 Case baseline 目录结构和历史版本可不同。
- **Rejected**: 在生产源码写死当前两个 baseline ID。

## 决策 6：重复版本与切分

- **Decision**: `junction:<mainnodeid>`、`segment:<segment_id>`、`case:<case_id>` 是稳定 group；五折由 seed+group hash 决定。
- **Rationale**: 当前 T03/T04 和两个 Segment 根存在不同 checksum 的重复业务 ID。
- **Rejected**: 按文件行或目录随机切分。

## 决策 7：Road 匹配

- **Decision**: 先按 canonical `id` 一对一匹配；未匹配对象再执行受距离门禁约束的确定性几何 fallback，并保留原因。
- **Rationale**: T06 source=1/2 多数保留输入身份，但模型可能产生新/变化 ID；两层匹配兼顾语义和几何。
- **Rejected**: 仅按 GPKG hash、仅按 ID 或无门禁最近邻。

## 决策 8：M0 依赖与入口

- **Decision**: 复用现有 GIS 依赖，只提供模块 callable；真实验证由 SpecKit validation 调用。
- **Rationale**: M0 尚未训练模型，无需 PyTorch；用户未要求扩大正式入口面。
- **Rejected**: 提前新增训练框架、repo CLI、root script 或 T10 stage。

## 决策 9：用户确认排除

- **Decision**: 用户确认排除的样本由参数化 `ApprovedExclusion` 进入 manifest；保留原始 lineage、split assignment 和 integrity evidence，但关闭全部训练 task mask，并与尚待复评的 quarantine 分开统计。
- **Rationale**: 2026-07-21 用户确认先排除 `T10-Error / 1213556_1263661` 并继续推进。
- **Rejected**: 在源码中硬编码 Case ID、删除原始 Case/baseline，或把用户排除伪装成数据自然通过。
