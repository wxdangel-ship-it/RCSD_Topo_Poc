# 标准 Skill 目录说明

本目录用于存放仓库级标准 Skill 包：

```text
.agents/skills/<skill-name>/
  SKILL.md
  references/
  scripts/
  assets/
```

规则：

- 标准 Skill 统一放在这里，不放在模块根目录。
- 模块根目录不放 `SKILL.md`。
- `SKILL.md` 只描述可复用流程，不承载模块长期真相。
- 模块长期真相写在 `modules/<module>/architecture/*` 与 `INTERFACE_CONTRACT.md`。

当前仓库初始化阶段尚未创建任何具体 Skill 包。
