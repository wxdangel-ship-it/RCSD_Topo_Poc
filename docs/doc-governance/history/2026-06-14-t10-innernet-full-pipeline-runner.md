# 2026-06-14 T10 内网全量端到端总控入口

## 背景

本轮工作树已经具备 Case 级 T10 端到端 runner，但用户明确要求提供内网全量执行脚本，而不是 Case 级 replay。已有 `scripts/t10_run_e2e_cases.sh` 只能消费 T10 Case package，不适合作为全量数据链路入口。

## 时间轴

1. 确认现有 T10 正式入口只有 Case 证据包打包和 Case 级端到端执行，缺少串联全量数据的总控入口。
2. 新增 `scripts/t10_run_innernet_full_pipeline.sh`，按 `T08 -> T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T07 Step3 -> T06 Step1/2 -> T06 Step3 -> T09` 串联既有模块脚本或 callable。
3. 全量 runner 默认读取 `/mnt/d/TestData/POC_Data`，所有阶段输出统一写入 `outputs/_work/t10_innernet_full_pipeline/<RUN_ID>/`。
4. 全量 runner 写入 `t10_innernet_full_pipeline_manifest.json`，记录原始输入、阶段 handoff 输出、最终 FRCSD Road/Node 与 T09 restriction 输出。
5. 同步更新 T10 README、架构约束、接口契约和 repo 入口登记表，将 Case 级入口与全量入口分开登记。
6. 内网首次手动指定输入运行时暴露 `SWSD_INPUT_NODES` / `SWSD_INPUT_ROADS` 易传反问题：T01 bootstrap 会在字段解析阶段报 `invalid literal for int() with base 10: '060a'`，错误位置滞后且不直观。
7. 在全量 runner 调用 T01 前增加 SWSD nodes/roads schema 角色校验：nodes 输入必须具备 node `id` 且不能像 road 层一样同时具备 `snodeid/enodeid`；roads 输入必须具备 `snodeid/enodeid`。若判断为传反，脚本在 T01 前直接 `[BLOCK]` 并输出明确提示。

## 业务逻辑变更

本次变更只新增执行编排入口，不修改 T01-T09 任何模块算法。

T08 在 T10 v1 callable 与 Case runner 中仍然保持独立，不被 Case 级 replay 调用；内网全量 runner 作为项目级总控脚本，可把 T08 作为独立前置阶段纳入全量执行链路。

Tool7/Tool8 默认使用 `auto` 模式：只有原始 SW 条件、车道、节点、道路输入齐全时才自动生成；否则要求调用方提供既有 `SW_RESTRICTION_TOOL7` 与 `SW_ARROW_TOOL8` 输出，避免静默伪造 T09 输入。

T08 Tool9 默认不启用；如内网需要在全量链路中使用 RCSD 清理输出，需显式设置 `RUN_T08_TOOL9=1` 或 `RUN_T08_TOOL9=auto`。

全量 runner 对手工指定的 `SWSD_INPUT_NODES` 与 `SWSD_INPUT_ROADS` 做入口层防呆校验。该校验只确认 T01 的输入角色是否符合最小 schema 预期，不根据局部数据内容推断新的业务字段语义。

## QA 覆盖

- CRS 与坐标变换：全量 runner 不做几何重投影，CRS 责任仍由各模块既有脚本和输出审计承担。
- 拓扑一致性：全量 runner 对关键 handoff 文件做存在性硬检查，不对拓扑做 silent fix。
- 几何语义可解释性：全量 runner 保留各模块原始阶段输出目录，不压缩或改写几何成果。
- 审计可追溯性：manifest 记录输入、输出、阶段顺序和日志目录。
- 性能可验证性：T03/T04/T05 worker 参数可通过环境变量显式覆盖，并保留每阶段 stdout log。

## 产物

- `scripts/t10_run_innernet_full_pipeline.sh`
- `modules/t10_e2e_orchestration/README.md`
- `modules/t10_e2e_orchestration/architecture/02-constraints.md`
- `modules/t10_e2e_orchestration/INTERFACE_CONTRACT.md`
- `docs/repository-metadata/entrypoint-registry.md`
