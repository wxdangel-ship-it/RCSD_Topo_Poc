# 02 约束

## 状态

- 当前状态：项目级约束说明
- 来源依据：
  - `SPEC.md`
  - `docs/ARTIFACT_PROTOCOL.md`
  - `AGENTS.md`

## 全局约束

- 当前阶段禁止迁移 Highway 业务模块实现。
- 当前阶段禁止创建具体 RCSD 业务模块。
- 当前输入数据组织方式先保持与 `Highway_Topo_Poc` 一致。
- 文档与实现必须分离：
  - 文档在 `modules/<module>/`
  - 实现在 `src/rcsd_topo_poc/modules/<module>/`
- 标准 Skill 统一放 repo root `.agents/skills/`，模块根目录不放 `SKILL.md`。

## 协作约束

- 项目内文档默认使用中文撰写。
- 中等及以上结构化治理变更优先走 spec-kit。
- 默认禁止新增新的执行入口脚本；新增前必须登记。

## 运行约束

- 项目工作目录默认位于 Windows `E:` 盘。
- 运行输出目录写入 `outputs/_work/`。
- 文本回传必须符合 `TEXT_QC_BUNDLE` 粘贴性约束。
