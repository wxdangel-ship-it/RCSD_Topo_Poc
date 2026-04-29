# 01 Introduction And Goals

## 1. 模块目标

T04 为分歧、合流、连续分歧 / 合流与复杂连续链路口生成道路面约束下的虚拟锚定面，并输出可追溯的发布层、审计层、review 图和 downstream node 状态回写结果。

当前目标不是重开业务语义，而是把 GitHub `main` 上已经固化的实现事实表达清楚：

- Step1-7 是当前正式业务链。
- Step7 最终状态机只允许 `accepted / rejected`。
- Anchor_2 full baseline 冻结为 `23 case / accepted = 20 / rejected = 3`。
- `857993 = rejected` 是人工验收确认后的正确结论。
- T04 正式 surface 主产物仍为 `divmerge_virtual_anchor_surface*`。
- downstream `nodes.gpkg` 与 `nodes_anchor_update_audit.csv/json` 只表达 representative node 的状态回写，写回值域为 `yes / fail4`。

## 2. 业务目标

- 用 Step1 admission 明确候选是否进入 T04。
- 用 Step2 local context 组织高召回的局部道路、节点、SWSD negative context 与 RCSD 上下文。
- 用 Step3 topology skeleton 把 case coordination skeleton 与 event-unit executable skeleton 分开。
- 用 Step4 fact event interpretation 解释局部事实、主证据、参考点、正向 RCSD 与受控恢复路径。
- 用 Step5 geometric support domain 形成 `must_cover / allowed_growth / forbidden / terminal_cut` 约束。
- 用 Step6 polygon assembly 在约束内生成单一连通最终面。
- 用 Step7 final publish 发布 surface、rejected、summary、audit、consistency 与 downstream nodes 结果。

## 3. 成功判据

- CRS、拓扑关系、几何语义与审计链路可解释。
- Step1-7 的输入、输出与失败原因不串层。
- batch / internal full-input 的 summary、audit、consistency report、surface 发布层与 downstream nodes 输出保持一致。
- frozen baseline 自动守住 `23 / 20 / 3`，且 `857993` 不被误改为 accepted。

## 4. 当前非目标

- 不新增 repo 官方 CLI。
- 不直接 import / 调用 / 硬拷贝 T03 模块代码。
- 不把 T04 surface 主产物改名为 T03 风格产物。
- 不保留最终 `review / review_required` 作为正式发布状态。
- 不把 RCSD 缺失、Step4 soft-degrade 或 review 提示直接等同于 Step7 最终失败。
