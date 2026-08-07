# 启动说明

## 当前状态

本分支已完成 `specify / plan / tasks`，尚未实现新网络、尚未训练、尚未读取冻结测试。
第一项实施工作是 T001–T004 合同冻结、特征来源审计和测试隔离门。

## SpecKit 自检

仓库分支统一使用 `codex/` 前缀，而当前内置脚本只接受三位数字开头的分支名；因此
本任务不运行会必然失败的 branch-name wrapper，也不为本任务改写共享 SpecKit 工具。
启动门直接核验当前分支、feature 目录、`spec.md / plan.md / tasks.md / research.md /
data-model.md / contracts/ / analysis.md` 完整性、占位符清零和 `git diff --check`。

## 实施硬门

任何 `.py` 写入前先检查目标文件当前字节数；历史大文件保持只读。首轮不得启动训练，
直到 64D/12D 特征逐维审计、Step1 防火墙、blind-test 隔离和完整输出 schema 测试通过。
