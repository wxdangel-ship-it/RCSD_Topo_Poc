# T09 Step1/2 restriction 候选唯一性履历

## 2026-06-11

### 背景

T10 `1885118` 复测中发现，T09 Step1/2 已恢复的 SWSD restriction 证据在 Step3 F-RCSD 限制输出中仍有明显缺口。抽查同一 Tool7 `CondID` 下的多条 `inLinkID / outLinkID` 记录后，发现 `CondID` 不是单条 link-pair 的唯一键；同一 restriction id 可对应多个进入 / 退出 link pair。

### 根因

Step1/2 证据索引优化后，候选 restriction 使用 `restriction_id` 提前去重。若同一 `restriction_id` 下第一条候选 link pair 与 movement 不匹配，后续真实匹配的 link pair 会被去重吞掉，导致恢复规则缺失。

### 业务逻辑变更

- restriction 候选的去重键调整为 `(restriction_id, in_link_id, out_link_id)`。
- 保留 `restriction_id` 作为业务限制编号，不再把它误用为单条候选证据唯一键。
- 不新增或反推任何 Tool7 字段语义；仅使用既有输入字段 `restriction_id / in_link_id / out_link_id` 区分候选粒度。

### 验证记录

- 单元测试新增同一 `restriction_id` 多 link-pair 场景，确认真实匹配候选不会被不匹配候选吞掉。
- `1885118` 基于 T07 Step3 后的 T06/T09 重放中，Step1/2 `restored_rules` 由 1101 提升到 1213，Step3 `restriction_count` 由 705 提升到 861。

