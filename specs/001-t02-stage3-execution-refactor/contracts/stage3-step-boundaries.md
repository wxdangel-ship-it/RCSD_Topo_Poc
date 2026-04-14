# Contract: Stage3 Step Boundaries

## Step3 - Legal Activity Space

职责：

- 生成当前模板允许的唯一合法活动空间
- 固化 must-cover 语义组覆盖要求
- 固化不可跨越的 DriveZone / opposite lane / foreign hard boundary

禁止：

- 不得被 Step4/5/6/7 反向扩大
- 不得在 Step6 cleanup 时偷偷外扩

## Step4 - RC Semantics

职责：

- 识别 `required RC / support RC / excluded RC`
- 生成 `stage3_rc_gap`

禁止：

- 不得决定 foreign 几何裁切
- 不得反向扩大 legal space

## Step5 - Foreign Hard Exclusion

职责：

- 把 foreign node / road-arm-corridor / rc context 建模为硬排除
- 输出可执行的 foreign trim model

禁止：

- 不得依赖 Step7 解释补做 foreign 识别
- 不得把 foreign 仅作为文本标签输出

## Step6 - Constrained Geometry

职责：

- 在 Step3 legal space 与 Step5 foreign hard exclusion 约束内生成几何
- 满足 Step1 must-cover 与 Step4 required RC must-cover
- 只允许有限优化

禁止：

- 不得通过 late cleanup 反向改写 Step3/4/5 语义
- 不得把 cleanup 变成补面洗白器

## Step7 - Final Acceptance

职责：

- 基于 Step3~6 的冻结结果输出 `accepted / review_required / rejected`
- 固定 `root_cause_layer / root_cause_type / visual_review_class`

禁止：

- 不得在 Step7 后再改几何
- 不得依靠字符串关键词反推步骤根因
