# 00 当前状态研究

## 当前状态

- 模块 ID：`t00_utility_toolbox`
- 当前阶段：`active / Tool1 done + Tool2/Tool3 implementation`
- 研究目标：确认 T00 当前的工具范围、统一几何口径和真实运行阻塞点

## 当前输入证据

- `specs/t00-utility-toolbox/spec.md`
- `modules/t00_utility_toolbox/INTERFACE_CONTRACT.md`
- 本轮 Tool2 / Tool3 任务书
- 当前 `scripts/` 与 `src/` 实现

## 当前观察

- `T00` 是项目内工具集合模块，不是 Skill，也不是正式业务生产模块
- 当前已纳入 Tool1 / Tool2 / Tool3
- Tool1 负责 `patch_all` 骨架和 `Vector/` 归位
- Tool2 负责全局 `DriveZone` 预处理与合并
- Tool3 负责全局 `Intersection` 预处理与汇总
- Tool2 / Tool3 沿用 Tool1 的“固定脚本 + `src` 模块 + 根目录日志摘要”风格

## 待确认问题

- 当前环境缺失默认 `D:\TestData\POC_Data\patch_all` 数据根，真实全量验证待上游数据可达后执行
