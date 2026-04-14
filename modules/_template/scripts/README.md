# 模块脚本目录

本目录只用于“模块内确有获批脚本、且 repo-level CLI 与 repo root `scripts/` 无法替代”的少数场景。

规则：

- 默认不在本目录创建具体脚本
- 默认优先使用 repo-level CLI 子命令或 repo root `scripts/` 作为官方入口
- 只有在任务书批准且入口已登记到仓库级 registry 后，才在本目录放模块内脚本
- 若模块当前没有模块内脚本，本目录可为空，甚至可不创建
