# T02 Stage4 正式需求文档修订报告

## 1. 本轮范围

- 工作类型：`docs-only`
- 模块范围：`T02`
- 阶段范围：`Stage4`
- 本轮未修改任何算法代码、测试逻辑、CLI / 参数实现，也未执行 push / PR / merge。

## 2. 本轮修改的文件

### 2.1 `modules/t02_junction_anchor/INTERFACE_CONTRACT.md`

- 重写了模块总览中的 Stage4 顶层定位与处理对象摘要。
- 重写了 `2.3A 数据源特性与精度约束` 中关于 SWSD / RCSD 的 Stage4 约束表述。
- 重写了 `2.10 Stage4 div/merge 虚拟面契约`：
  - 顶层定位
  - 处理对象与非目标
  - 七步正式业务定义
- 修订了 `3. Outputs` 下的 `最终成果路口面统一输出约束`：
  - 统一 `mainnodeid / kind`
  - 新增 Stage4 最终 polygon 图层应稳定承载的审计属性字段
  - 明确 `acceptance_class / acceptance_reason` 为建议同步固化字段
- 修订了 `Stage3 / Stage4 成果审计与目视复核`：
  - 正式写明 Stage4 复用 Stage3 的双线并行审计模板
  - 明确“复用模板，不继承 Stage3 业务语义”
- 重写了 `Stage4 状态与失败口径`：
  - Step7 三态
  - 条件性 RCSD 硬约束
  - `mainnodeid_out_of_scope` 的正式含义
  - `review_required / rejected` 的边界

### 2.2 `modules/t02_junction_anchor/architecture/06-accepted-baseline.md`

- 重写了 `## 10. 阶段四：stage4，diverge / merge virtual polygon`：
  - `10.1 当前版本定位`
  - `10.2 当前处理对象与非目标`
  - `10.3 七步正式业务定义`
  - `10.4 审计、目视复核与成果字段`
  - `10.5 当前阶段性边界与未来合并方向`
- 修复了原文中 Stage4 段后续章节编号冲突：
  - `当前已落地 / 已固化内容` 调整为 `## 11`
  - `当前仍需继续验证 / 修正的内容` 调整为 `## 12`
  - `当前推荐对齐原则` 调整为 `## 13`

### 2.3 `modules/t02_junction_anchor/README.md`

- 在 `模块定位` 下新增 `Stage4 摘要`：
  - 当前定位
  - 处理对象
  - 当前非目标
  - 审计 / 目视复核复用边界
  - 最终成果输出摘要
- 修订了 Stage4 入口说明，去掉“所有 `kind / kind_2 = 128` 都进入 Stage4”的误导表述，改为“连续分歧 / 合流聚合后的 complex 128 主节点”。
- 修订了 Stage4 自动发现说明，使其与正式契约一致。

### 2.4 `specs/t02-junction-anchor/spec.md`

- 修订了文档定位说明，不再把本文件表述为“只保留 stage1 初始基线”的单一工件。
- 新增 `7.2 Stage4 正式需求文档修订同步（2026-04）`：
  - 明确本轮是文档收敛，不是代码重构
  - 指明 Stage4 正式契约所在文档
  - 同步四类 Stage4 正式口径
  - 明确 Stage3 模板复用边界

## 3. 清除的旧口径冲突

### 3.1 Stage4 只处理 `kind_2 in {8,16}`

- 旧口径：
  - 将 Stage4 处理对象写成单纯的 `kind_2 in {8,16}` 候选，或把所有 `kind / kind_2 = 128` 一并视为 Stage4 对象
- 新口径：
  - Stage4 当前处理简单 div/merge 候选
  - 以及连续分歧 / 合流聚合后的 complex 128 主节点
  - `kind` 与 `kind_2` 在候选识别语义上等价

### 3.2 RCSD 是无条件刚性约束

- 旧口径：
  - 将 RCSD 覆盖直接写成无条件硬约束
- 新口径：
  - 只有在对应事实路口存在对应 RCSD 挂接时，RCSD 覆盖 / 容差才构成条件性硬约束
  - 若事实路口缺失对应 RCSD 挂接，不以 RCSD 未覆盖作为单独失败条件

### 3.3 Step2 只是 patch 局部过滤

- 旧口径：
  - Step2 更像 patch 级局部过滤或局部补丁处理
- 新口径：
  - Step2 明确冻结为 `DriveZone` 硬边界内的高召回事实事件局部上下文构建
  - 同时承担正向召回上限与负向排除上下文组织

### 3.4 Step3 作为常规失败步骤

- 旧口径：
  - 把 Step3 里的拓扑不稳或实现保底路径直接写成常规业务失败
- 新口径：
  - Step3 是拓扑成骨架步骤
  - 原则上不作为常规业务失败步骤
  - 它负责产出骨架并暴露不稳定性

### 3.5 Step4 只是 DivStrip 分析

- 旧口径：
  - 把 Step4 写成主要做 `DivStrip` 命中分析
- 新口径：
  - Step4 正式冻结为“事实事件解释层”
  - `DivStrip` 只是主证据链的第一优先级
  - 还包括 `continuous chain / multibranch / reverse tip / fallback`

### 3.6 Step7 的 `rejected` 只来自异常 handler

- 旧口径：
  - `rejected` 更偏向运行异常或 handler 失败
- 新口径：
  - `rejected` 是正式业务状态
  - 表示无合法结果或违反明确硬业务约束
  - 不再只承接异常 handler 语义

## 4. 本轮新增冻结的内容

- Stage4 顶层定位：
  - 独立补充阶段
  - 当前不回写 `nodes.is_anchor`
  - 当前不并入统一锚定结果
  - 当前不承担主流程最终唯一锚定闭环
- Stage4 七步正式业务定义。
- Stage4 对 Step2 的 `50m / 200m` 召回上限与“不得越过相邻语义路口”约束。
- Stage4 对 Step5 “近似垂直横截面”的正式几何构造要求。
- Stage4 对 Step7 三态、条件性 RCSD 硬约束、结果包落盘责任的正式定义。
- Stage4 复用 Stage3 双线审计与三态 PNG 样式契约的正式口径。
- Stage4 最终成果 polygon 图层的属性字段契约：
  - `mainnodeid`
  - `kind`
  - geometry=`EPSG:3857`
  - 审计字段集合
  - 建议同步固化 `acceptance_class / acceptance_reason`

## 5. 故意没改的内容

- 未修改任何 `.py`、测试、脚本、CLI、参数、运行方式实现：
  - 本轮任务书明确要求 `docs-only`
- 未把当前实现现状逐条原样写成正式需求：
  - 只保留与本轮任务书一致、且已对齐的实现事实
  - 对实现里的临时路径、保底异常路径、调参痕迹，未升级为正式业务规则
- 未修改 `modules/t02_junction_anchor/AGENTS.md`：
  - 本轮任务书未要求
  - 它不是 Stage4 正式业务契约承载文档

## 6. 讨论材料与取材说明

- 用户指定的已有讨论材料并不位于仓库根目录，实际取材路径为：
  - `outputs/_work/t02_stage4_audit_20260414_172419/STAGE4_AUDIT_REPORT.md`
  - `outputs/_work/t02_stage4_requirement_alignment_20260414_180626/STAGE4_CURRENT_REQUIREMENT_DISCUSSION.md`
- 本轮以任务书为裁决依据，并以以上讨论材料与现有正式文档作为收敛参考。

## 7. 仍未落地到代码的内容

- 本轮只完成正式契约修订，未进入实现层修复。
- 以下内容后续仍建议进入代码重构 / 算法修复轮次：
  - Step1~Step7 与当前实现链路的一致性校验
  - Stage4 结果包字段与 polygon 图层字段的全面对齐
  - 目视分类 `V1~V5` 与程序 `accepted / review_required / rejected` 的一致性审计
  - 条件性 RCSD 硬约束在实现层的稳定落地
  - Stage4 最终 polygon 几何边界、局部支撑域与负向排除对象的实现层一致性验证

## 8. 本轮结论

- 本轮已把 Stage4 的正式业务需求、审计口径、目视复核口径和输出面属性字段规则统一修订进仓库文档。
- `INTERFACE_CONTRACT.md` 已作为长期主契约承载 Stage4 正式源事实。
- `06-accepted-baseline.md`、`README.md` 与 `spec.md` 已同步到不打架的版本。
- 本轮为纯文档收敛，不代表代码已自动满足新契约；后续仍需按新契约进入实现层审计与修复。
