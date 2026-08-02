# Research：当前基线与候选方案评估

## 1. 当前主干事实

- 基线 commit：`7c8b832edd229b807dc4478aa868a7e0ac19957c`。
- 本地 `origin/main` 指向该 commit；本轮启动时 `git fetch origin main` 因
  `Host key verification failed` 未能刷新，最终交付前必须重新验证远端指针。
- 根工作区存在 P05 未提交改动，本轮使用独立干净 worktree，不触碰根工作区。
- QGIS runtime：QGIS `3.40.14`、GDAL `3.12.1`、PROJ `9.7.1`、GEOS `3.14.1`，
  PyQGIS import 已通过。

## 2. 当前主干的直接缺口

QA 54 Case 当前为 `17 accepted / 37 rejected`。明确偏差：

- `706399`：association A/established，但 Step6 因 semantic intra-RCSDNode line coverage
  失败；实际已存在完整 RCSD 语义路口 `5885149759931655`。
- `709492`：association A/established，但 Step6 几何求解失败；实际应沿真实 Road 链确认两个
  RCSD 语义路口，不应以 alias 直线距离代替 Road-surface access。
- `724917`：Step3/T07 旧门禁不一致，目标到 DriveZone 的实际 gap 约 `1.424m`；用户已确认统一
  为 `2m`。
- 新 QA 快照 `520394575 / 522008569 / 522806716 / 622700016` 均被 accepted；旧结论曾将其
  按 CaseID 冻结为 T12 正样本，但用户已确认当前 QA 输入属于另一数据版本，该冻结结论撤销。

旧数据当前明确假拒绝至少包括 `991380 / 1633175 / 47408750 / 54265802 / 605652585`；
明确假接受至少包括 `507831701 / 522008569 / 522806716`。

## 3. 未合并实验分支的可复用性

只读重放 `codex/t03-quality-closure-20260730` 的通用实现：

- QA 54 从 `17/37` 改为 `35/19`；
- 正确修复 `706399 / 709492` 和另 16 个 A 类 geometry false rejection；
- 旧数据正确修复 `991380 / 1633175 / 47408750 / 54265802 / 605652585`；
- 旧数据能把 `507831701 / 522008569 / 522806716` 保守拒绝；
- 但没有修复 `724917`，且把当前 QA 快照的 T03 拒绝直接解释为固定 T12 正样本；
- 并把人工确认应失败的 `74421922` 错误放行为 accepted。

结论：canonical lookup、ownership、Road-surface、business connectivity 和 surface
regularization 可以作为候选实现复用，但必须补全当前快照 raw topology 门禁和复杂场景负回归，
不得直接搬运或直接合并。

## 4. 关键设计决策

1. **距离门禁只解决接触，不证明锚定**：`2m` 仅用于已定义的 Road/DriveZone/surface access，
   不得替代 Road endpoint、Direction 或 ownership。
2. **surface 与 anchor outcome 分层**：几何存在不代表 RCSD 路口拓扑完整；Step7 发布前必须检查
   当前模板需要的 raw topology。
3. **Direction-first**：Road 链必须严格按 `direction 0/1/2/3` 建图；mainNode/alias 只做分组和
   portal，不生成零长度通路。
4. **MultiPolygon 业务判定**：比较业务终端在原始合法 Road surface 和输出面中的连通分区；不按
   Polygon/MultiPolygon 类型设硬规则。
5. **无效几何显式化**：不因 `union` 后有效而隐藏原始自相交；任何合法化都必须有独立审计，无法
   证明语义保持时阻断。
6. **测试 ID 与生产规则隔离**：Case ID 只存在于 truth registry、测试参数和验证报告。

## 5. Scheme A 验证结果

- `768683 / 830724 / 952797 / 992932 / 1049277 / 520394575 / 622700016` 已由
  canonical raw portal、2m surface access、required carrier 与 business connectivity 通用规则稳定
  修复；生产代码未出现 CaseID。
- QA 当前快照最终为 `43 accepted / 11 rejected`；历史 T03 为 `73 / 2`，历史 T03_Error 为
  `242 / 16`，人工成功/失败保护集无回退。
- 对 11 个 QA residual rejected Case 的 T12 独立重验只确认 `522806716`：存在已局部锚定的
  SWSD required movement，但 FRCSD 输出臂缺少 Direction 合法 outgoing 角色。其余均有等价 carrier、
  跨层/constraint、无效输入、局部 ownership 证据不足或 T03 来源不足的排除理由。
- `74421922` 由复杂场景的 nonunique ownership/anchor topology 保守拒绝，未被 surface 收敛覆盖。
- 无效 DriveZone 不做 silent fix；无法证明拓扑语义保持的 residual Case 明确 input-blocked。派生
  normalization 仅在审计证明 component 与 area 不变时继续，且不回写输入。
- 54 个 QA Case 均有 terminal result，所有状态变化均可由正式审计字段解释。
