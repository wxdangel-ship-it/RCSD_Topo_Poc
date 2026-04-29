# Plan

## 目标

将 T03 RCSD 契约从旧 `required / support / excluded` 单层消费口径扩展为 `related / support / local_required / foreign_mask` 分层语义，同时保持正式输出文件名、Step3~Step7 判定规则与入口稳定。

## 实施步骤

1. 修订模块契约与架构文档，定义三层语义、字段归属、review 渲染口径与兼容边界。
2. Step4 产出 `related_*` 字段，并记录 required-core 一跳 outside-scope 补证与多点 `mainnodeid` 复合语义组的审计证据。
3. Step5 将 `required / support / related_rcsdroad_ids` 分别从 hard negative 集合中排除，新增 `foreign_mask_source_rcsdroad_ids`。
4. Step6 在 audit/status 中暴露 `related / local_required / foreign_mask` 字段，不改变 must-cover 或 acceptance 判定。
5. Review render 用强语义 `related_rcsdroad_geometry` 绘制深红 RCSDRoad，`support_rcsdroad_geometry` 保持 amber 辅助证据表达。
6. 补 synthetic、真实 case 与 render 口径测试。

## 风险控制

- 不改变 `association_required_* / association_support_* / association_excluded_*` 文件名。
- 不新增官方入口。
- 不修改 Step3、Step6、Step7 的业务判定优先级。
- 对 outside-scope related 的识别仅限 active RCSD 图内、从 `required_rcsdroad_ids` 经 `degree = 2` connector 一跳补证的 road；support/group related 不作为外扩种子。
- 对空间紧凑的多点 `mainnodeid` group 只扩展 node 语义整体，不自动扩展该 group 的全部 incident road；road 仍需自身命中 local / outside-scope related 规则。

## 验证

- targeted pytest：Step5、706389/707476/709431 regression。
- broader pytest：association、association contract、Step5、Step6/Step7 geometry、705817/706389 等 case regressions。
- `git diff --check`。
