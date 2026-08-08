# 启动说明

## 当前状态

本分支已完成 T001–T020。T017-A 完成对象身份表示、pointer-set cardinality 和 Road
多打断 decoder 修正；用户授权的 T017-R1 及其 REQUIRED coverage loss 修正复验均已执行。
当前状态为 `T017_R1_REPRESENTATION_NO_GO`：最终 teacher/free 完整 exact 为 `7/8`，仍有
一条虚拟面 cardinality 未过拟合。冻结测试仍未读取、正式 canary 未启动；不得进入 T021。

## SpecKit 自检

仓库分支统一使用 `codex/` 前缀，而当前内置脚本只接受三位数字开头的分支名；因此
本任务不运行会必然失败的 branch-name wrapper，也不为本任务改写共享 SpecKit 工具。
启动门直接核验当前分支、feature 目录、`spec.md / plan.md / tasks.md / research.md /
data-model.md / contracts/ / analysis.md` 完整性、占位符清零和 `git diff --check`。

## 实施硬门

任何 `.py` 写入前先检查目标文件当前字节数；历史大文件保持只读。64D/12D 特征逐维
审计、Step1 防火墙、blind-test 隔离、完整输出 schema、候选约束 decoder、确定性
materializer 和安全 evaluator 已通过训练前合同测试。T017 不得读取冻结测试或扩展到
正式 canary；失败即停在表示/合同层。

T017 运行工件位于 ignored output
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_overfit_20260808/`。
其中候选目录是 `TRAINING_ORACLE_ONLY`，不能解释为真实推理候选生成能力。

T017-R1 训练前 dry-run 工件位于
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r1_readiness_20260808/`；
其中 `training_executed=false`、`optimizer_step_executed=false`、blind access `=0`。

T017-R1 原始训练和 REQUIRED coverage 修正复验工件分别位于：

- `outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r1_overfit_20260808/`；
- `outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r1a_overfit_20260808/`。

两次结果均为 `REPRESENTATION_NO_GO`，blind access 均为 `0`；不得用追加 epoch、seed 或
阈值搜索把它解释为 PASS。
