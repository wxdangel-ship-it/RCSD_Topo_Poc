# 04 方案策略

## 状态

- 当前状态：项目级方案策略说明
- 来源依据：
  - `SPEC.md`
  - `docs/doc-governance/current-module-inventory.md`
  - `docs/repository-metadata/repository-structure-metadata.md`

## 策略摘要

当前采用“抽象复用、分层落位、按层收口”的治理策略：

1. 直接复用通用脚手架与工作流资产
2. 用项目级 source-of-truth 固化仓库规则、生命周期与模块名单
3. 让已登记模块的正文事实下沉到模块级 source-of-truth
4. 保持 `modules/_template/` 作为后续新模块统一起点
5. 通过仓库元数据持续收敛目录职责、执行入口与结构债信息

## 分层策略

- `SPEC.md` 作为顶层项目规格基线
- `docs/architecture/` 作为项目级长期架构文档面
- `modules/<module>/architecture/` 作为模块级长期架构文档面
- `AGENTS.md` 只保留持久执行规则
- repo root `.agents/skills/` 承载标准可复用流程
- `specs/<change-id>/` 承载变更专用推理与执行计划

## 数据兼容策略

- 当前 patch 输入组织方式先与参考仓库保持一致
- 该兼容约束只解决初始化阶段的工程一致性问题
- 后续若 RCSD 业务需要改变数据布局，必须通过独立任务和文档写回
