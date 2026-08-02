# Implementation Plan：T03 全量 Case 准确性闭环

## 产品

- 建立 per-dataset-snapshot 真值注册表，区分 formal baseline、用户后续裁决和未确认 Case。
- 交付结果同时展示 surface publication、anchor outcome、relation eligibility 和 T12 quality verdict，
  避免把单一状态解释为全部业务正确。
- 以误判为零作为硬门，不以 accepted 数增加作为验收。

## 架构

1. 保持 T03 Step1-Step7 和入口不变。
2. 在 Step3 把 single-sided/center 的边界接触门禁收敛到共享 `2m` 语义，保留 legal space 冻结。
3. 在 Step4 复用 deterministic canonical mainNode lookup 和 Class B junction ownership gate。
4. 在 Step6 分离：硬约束、Road-surface 业务连通域、受约束边缘追踪/平滑、形态风险审计。
5. 在 Step7 增加模板需求与 Direction raw topology 的 anchor completeness gate；对 support-only、
   terminal collapse、unmatched support component 和复杂歧义输出明确 reason/audit。
6. T05 只修 canonical lookup，不改变 Phase 1/Phase 2 handoff。
7. T12 只消费并用当前 raw Road/Node、Direction、SWSD 必需通行与等价 carrier 重验 T03 候选；
   不得把 T03 的拒绝状态、reason、unmatched component 或 connected core 直接当作质量结论，
   也不得在 T12 重写 T03 算法。QA 当前快照不预设正样本数量。

## 研发

- 从旧实验 diff 中逐文件选择通用实现，禁止整体复制未审计工作树。
- 修改任何 `.py` 前先记录当前字节数；接近 100KB 的职责放入现有小模块或新增内部模块，且不新增
  启动入口。
- 先实现数据/拓扑审计函数和 synthetic tests，再接 Step4/Step6/Step7。
- 所有被丢弃的 RCSDNode/Road、component、alias transition 和 geometry normalization 都写审计。
- 不修改输入文件，不新增依赖。

## 测试

### 单元

- canonical mainNode 优先、alias 顺序无关、冲突/缺失审计；
- `2m` 内/外边界门禁；
- Direction 0/1/2/3 raw graph；
- merge-only terminal collapse、完整 split+merge、unmatched support component、复杂歧义；
- source/output connectivity partition 等价；
- legal/direction/foreign/must-cover/required carrier 不退化；
- 无效几何不 silent fix。

### 真实 Case

- QA 54 全量；
- legacy T03 78 目录（按契约有效执行 75）；
- legacy T03_Error 258；
- 历史 65 Case visual baseline；
- 本轮人工 success/failure truth registry；
- T12 QA 当前快照的 carrier-complete 防误报集、输入/跨层排除集和证据驱动确认集。

### 消费回归

- T03 全量测试；
- T05 全量测试；
- T06 全量测试；
- T12 Junction/真实 Case 测试。

## QA

- 运行前验证输入指纹和 CRS；指纹漂移必须显式生成新快照，不复用旧真值。
- 对 accepted surface 执行 QGIS/PyQGIS overlay gate，输出 per-layer/overall ratio 和 fail reasons。
- 机器门禁之外生成全量 QGIS review 图；人工确认仍由用户完成，机器不得根据图片回写 formal status。
- 输出前后状态 diff、reason diff、geometry metrics、topology partition、invalid geometry audit。
- 记录 wall time、阶段耗时、吞吐、峰值 RSS；与当前主干同机对比。

## 风险控制

- 旧实验方案存在把 `74421922` 放行的已知风险，必须有负回归后才可进入主实现。
- `12777955` 有争议，只能保持保守状态并输出证据，不纳入准确率分母。
- 原始无效 DriveZone 不能因 visual success 被 silent repair；需要明确 normalization contract。
- 同 ID 跨数据根语义可能变化，所有回归键使用 `dataset_snapshot + case_id`。

## 交付门

1. 用户确认真值误判为 0；
2. 所有状态变化逐 Case 可解释；
3. 三套全量、模块测试、GIS 五项和性能门全部通过；
4. 源码无对象 ID、输入无修改、`git diff --check` 和 code-size audit 通过。
