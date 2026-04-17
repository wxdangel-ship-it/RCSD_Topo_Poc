# T03 / Phase A Step3 repair closeout plan

## 1. 文档与治理

- 仅修复本轮 `Step3` 契约收口，不重写总体 spec。
- 统一 `INTERFACE_CONTRACT.md / spec.md / README.md / architecture/03-context-and-scope.md` 的修复轮口径。
- 明确 `input_gate_failed` 只作为前置输入门禁 `reason`，不新增第四种状态。
- 将 `922217 / 54265667 / 502058682` 记录为默认全量验收排除集，并保持显式点名单 case 的单独复跑能力。
- 本 patch round 只做增量补丁，不覆盖旧结论；README 需补齐操作者口径，明确 patch round 不得把 baseline partial 写成 fully complete。

## 2. 模块实现

- 本轮不扩展模块骨架，只为后续代码修复保留一致契约面。
- Step3 修复目标聚焦 `Rule D / Rule E / Rule F / Rule G` 与 Anchor61 真实验收。
- `Rule D` 需改为：无更早稳定边界时 `50m fallback` 允许直接成立，不自动进入 `review`，仅保留审计字段。
- `Rule E` 需降格明示为 `single_sided opposite-side guard baseline partial`，正式文档和审计文案统一改成 `opposite road / semantic node / near-corridor proxy` 口径，不再保留 lane 级护栏残留说法。
- 对双 node `single_sided_t_mouth` 追加两条规则：两 `node` 间 bridge 进入 `allowed-space` 主通路；共享 `2进2出` `node` 作为 through-node 时不中断主通路。

## 3. 输出结构

- run root：
  - `preflight.json`
  - `summary.json`
  - `step3_review_index.csv`
  - `step3_review_flat/`
  - `cases/<case_id>/...`
- 每个 case 固定 7 个业务输出。
- run 级 summary 需要补齐 `expected_case_count / actual_case_dir_count / flat_png_count / tri_state_sum / tri_state_sum_matches_total / missing_case_ids / failed_case_ids / rerun_cleaned_before_write`。

## 4. 验证

- 补齐规则级回归与 run 级 summary 回读验证。
- 使用系统 `python3` 跑测试与真实 Anchor61。
- 验证平铺 PNG、索引、summary 与 case 级产物完整，且 `missing_case_ids / failed_case_ids` 为空。
- 默认全量验收统计需同步记录 `excluded_case_ids / excluded_case_count`，避免将硬门禁 case 混入 run 级口径。
- 验收口径固定写明：原始 Anchor `61`，默认正式全量验收 `58`，`excluded_case_ids` 保持 `922217 / 54265667 / 502058682`。

## 5. 发布

- 分支：`codex/t03-phasea-step3-legal-space`
- 本轮以 repair closeout 为目标，建议 commit 只覆盖文档收口、规则修复、测试补强、验收结果更新
- push 后更新现有 Draft PR 描述，明确本轮仍只做到 `Step3`
