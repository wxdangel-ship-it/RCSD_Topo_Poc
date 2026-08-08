# 启动说明

## 当前状态

本分支已完成 T001–T021、T023。当前状态为
`T021_P1_COMPLETE_AWAITING_T022_AUTHORIZATION`：固定 seed `20260821` 在 4,288 条非 blind
开发记录上完成 9 epoch teacher-forcing 训练并由 patience `4` 自动 early-stop；best 为
epoch 5，validation teacher total `5.0001326037`。固定 split 为 `3,645/643`、Case-group
跨 split 为 0、blind access 为 0。该 checkpoint 仍为 `T021_TEACHER_FORCED_COMPONENT_ONLY`，
正式 free-run/canary 未启动，冻结 105 条 blind test 仍未读取。

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

T021 训练前工件位于
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t021_readiness_20260808/`：

- `manifest.json`：136 对 source/split 分片，4,288 条 feature/label 物理隔离 cache；
- `readiness-summary.json`：全量 Step1 防火墙与真实 CUDA 前向/loss；
- `training-preflight.json`：固定 seed `20260821`、hidden dim `384`、动态 token batch 和
  训练输出目录，只校验配置，不创建 optimizer。

T021 训练与完成审计工件位于
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t021_teacher_forcing_seed_20260821/`。
同 seed 初始化到 best checkpoint，validation teacher/free-condition total 分别下降
`74.60%/67.16%`，证明 P1 可学习；best 的 teacher/free 差距仍为 `1.6190376015`，且强 Gold
free total 为 `8.8208365122`。下一步只能在用户明确授权后进入 T022 scheduled sampling；
候选目录仍为 `T021_TEACHER_ORACLE_ONLY`，不能解释为真实推理候选生成或正式 free-run 能力。

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

T017-R2 无训练 readiness 工件位于
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r2_readiness_20260808/`；
其中 `training_executed=false`、optimizer/checkpoint 均未创建、blind access `=0`。

用户授权的 T017-R2 正式工件位于
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r2_overfit_20260808/`；固定
8 条强 Gold 的 teacher/free 完整 exact 均为 `8/8`，blind access `=0`。该 PASS 只证明
绑定候选上的表示与完整 heads 可学习，不代表跨 Case 泛化或真实推理候选能力。
