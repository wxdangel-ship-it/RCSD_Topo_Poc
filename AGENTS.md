# 仓库级执行规则

- 主入口：先读 `docs/doc-governance/README.md`；需要理解当前仓库结构时，再读 `docs/repository-metadata/README.md`。
- 源事实优先级：项目级源事实以 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md` 为准；模块级源事实以 `modules/<module>/architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- 边界：`AGENTS.md` 只放 durable guidance；标准可复用流程统一放 repo root `.agents/skills/<skill-name>/SKILL.md`；模块根目录不放 `SKILL.md`；`modules/_template/` 仅作为模板，不是业务模块。
- 文档语言：项目内文档默认中文；参数、代码、命令、路径、模块标识、配置键、接口字段可保留英文。
- 执行环境：内网与外网默认都在 WSL 下执行；若任务书或用户提供的是 Windows 路径，必须先转换为对应的 WSL 路径（如 `E:\Work\RCSD_Topo_Poc` -> `/mnt/e/Work/RCSD_Topo_Poc`）再继续。
- 执行边界：外网验证、外网数据检查与本地工作区操作属于 Agent 可执行范围；内网环境、内网数据拉取与内网命令执行默认仅由用户操作。Agent 不得将内网操作误表述为自己已实际执行，除非用户明确提供了可执行的内网访问能力。
- GIS 质量要求：在涉及 GIS / 拓扑 / 空间数据处理的任务中，Agent 必须以顶级 GIS 算法工程师标准执行，优先保证 CRS 与坐标变换正确性、拓扑一致性、几何语义清晰、结果可解释、审计可追溯、性能可验证；禁止用 silent fix、黑箱规则或未说明的几何假设掩盖问题。
- 规则约束：禁止根据局部样本、人工真值或单次冒烟结果，自行反推上游字段语义并直接固化为强规则；若样本现象与已确认语义冲突，必须先基于数据分析列出矛盾点，并向用户确认后再调整规则。
- 字段启用约束：未在项目 / 模块源事实文档中正式启用的输入字段，不得进入 Step1 / Step2 强规则；字段一旦正式启用，必须同步写入项目级约束与对应模块契约，说明其当前可用语义、适用范围与未确认边界。
- 文件体量：单个源码 / 脚本文件超过 `100 KB` 视为结构债；后续变更若必须触碰超阈值文件，先给出拆分计划或结构整改说明。
- 执行入口：默认禁止新增新的执行入口脚本；新增入口必须有任务书批准，并登记到 `docs/repository-metadata/entrypoint-registry.md`。
- 详细约束：`docs/repository-metadata/code-boundaries-and-entrypoints.md`。
- 冲突处理：若任务书与源事实文档冲突，必须列出冲突点并停止，请求确认。
- 分支与 spec-kit：中等及以上结构化治理变更优先使用 spec-kit；不在 `main` 上直接做结构化治理变更。
- 范围保护：无明确任务时，不创建具体业务模块实现，不修改未来模块接口假设，不把骨架治理轮次顺手扩大为业务算法开发。
