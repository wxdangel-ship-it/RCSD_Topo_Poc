# 启动说明

## 当前状态

本分支已完成 T001–T016、T018–T020 的训练前实现与合同测试；尚未训练、尚未读取冻结
测试。下一项工作是 T017：仅在训练折内用小批强 Gold 执行表示 overfit 门，需用户明确
授权后才能启动。

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
