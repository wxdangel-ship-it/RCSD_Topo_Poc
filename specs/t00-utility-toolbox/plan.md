# T00 Utility Toolbox 计划

## 1. 当前阶段说明

T00 的文档基线已完成，当前已补入 Tool1 的最小可执行实现，用于后续在内网环境直接运行 Patch 数据整理任务。

当前阶段仍保持轻量范围：只实现 Tool1，不创建 Tool2+，不增加额外框架，不补业务无关能力。

## 2. 文档组织计划

T00 当前文档组织分为两层：

- `specs/t00-utility-toolbox/`
  - `spec.md`：固化 T00 与 Tool1 的需求基线
  - `plan.md`：说明当前阶段与下一阶段衔接方式
  - `tasks.md`：拆分本轮与下一阶段的任务边界
- `modules/t00_utility_toolbox/`
  - `README.md`：模块入口说明
  - `AGENTS.md`：后续 Agent / CodeX 执行约束
  - `INTERFACE_CONTRACT.md`：轻量接口契约
  - `architecture/*`：模块级长期文档基线

`README.md` 不替代规格与契约；稳定语义以 `spec.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

## 3. Tool1 的实现边界

后续编码只能围绕当前已确认的 Tool1 范围展开：

- 目录骨架初始化
- `Vector/` 数据归位
- 复跑覆盖
- Patch 级异常不中断全量
- 目标根目录日志与摘要

后续编码不得越过当前规格，额外补入点云、轨迹、坐标转换、几何修复、图层分析或复杂 manifest 治理。

## 4. 下一阶段计划

下一阶段应围绕当前已落仓的 Tool1 固定脚本继续收口：

- 在内网数据环境执行首轮真实整理
- 基于真实运行结果复核日志与摘要字段是否足够
- 视需要补最小测试或补充实现细节，但不得扩张 Tool1 范围
- 待 T01 完成后，与其它模块一起统一下拉 GitHub

## 5. 暂缓项

当前明确暂缓：

- Tool2 及以上工具收录
- T00 的架构扩展设计
- 历史文档 `history/*`
- 更复杂的日志格式与 manifest 体系
- 任何超出 Tool1 需求基线的新功能

后补原则是：仅当 Tool1 文档与实现闭环稳定后，再为新增工具单独补规格并进入评审。
