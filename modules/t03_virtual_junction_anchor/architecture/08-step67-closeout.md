# T03 / Step67 Clarified Formal Stage Closeout

## 1. Scope

- scope: `T03 / Step67 clarified formal stage` on top of frozen `Step3` and established `Step45` baseline
- templates:
  - `center_junction`
  - `single_sided_t_mouth`
- non-goals:
  - `diverge / merge / continuous divmerge / complex 128`
  - rewriting `Step3 allowed space / corridor / 50m fallback`
  - freezing solver constants as long-term contract
  - promoting `Step67` to repo official CLI in this round

## 2. Delivery Mode

- current formal run root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step67_phase/20260419_t03_step67_formal_v015`
- execution surface: module-internal `run_t03_step67_batch()`
- repo official CLI status:
  - `Step67` still has **no** repo official CLI
  - current official CLI remains `t03-step45-rcsd-association`

## 3. Clarified Formal Conclusions

- `Step6` is a constrained geometry stage, not a cleanup-driven rescue layer
- `Step7` machine state is binary:
  - `accepted`
  - `rejected`
- `V1-V5` remain visual audit classes only
- `support_only` remains a conservative `Step45` intermediate state and can converge to `Step7 accepted`
- `Step5` no longer provides hard polygon foreign context
- `Step6` hard negative mask is currently limited to road-like `1m` masks
- `Step45` now formally applies `RCSD 调头口过滤` upstream:
  - matched `u-turn RCSDRoad` is treated as non-existent in current-case semantics
  - filtering happens before `degree2 connector / chain merge / required-support-excluded`
- `degree = 2` connector `RCSDNode` itself does not become semantic core; its connected candidate `RCSDRoad` chain is merged upstream before `required / support / excluded` classification
- `Step6` now follows `boundary-first + local required RC`:
  - directional boundary is a final hard cap
  - `required RC must-cover` only applies to `local required RC` inside the directional boundary
- 当冻结 `Step3` 对 `single_sided_t_mouth` case 应用 `two_node_t_bridge` 时，`Step67` 现在会显式继承该 bridge corridor 进入 directional boundary / polygon seed，避免横方向口门截断后出现中心断开、多组件狭长残留

## 4. Formal Acceptance Scope

- raw_case_count: `61`
- default_formal_case_count: `58`
- excluded_case_ids:
  - `922217`
  - `54265667`
  - `502058682`
- effective acceptance rule:
  - 默认未传 `--case-id` 时，正式全量验收按排除上述 `3` 个 case 后的 `58` 个 case 运行
  - 显式传入 `--case-id` 时，不应用默认排除集

## 5. Batch Result

- run_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step67_phase/20260419_t03_step67_formal_v015`
- case_dir_count: `58`
- flat_png_count: `58`
- missing_case_ids: `[]`
- failed_case_ids: `[]`
- Step7 result distribution:
  - `accepted = 55`
  - `rejected = 3`
- visual distribution:
  - `V1 = 54`
  - `V2 = 1`
  - `V4 = 3`
  - `V5 = 0`

Reference files:

- `outputs/_work/t03_step67_phase/20260419_t03_step67_formal_v015/preflight.json`
- `outputs/_work/t03_step67_phase/20260419_t03_step67_formal_v015/summary.json`
- `outputs/_work/t03_step67_phase/20260419_t03_step67_formal_v015/step67_review_index.csv`

## 6. Representative Recoveries

- `698330`
  - `accepted / V1`
  - selected-road longitudinal segment no longer gets incorrectly shortened by foreign handling
- `706389`
  - `accepted / V1`
  - `single_sided_t_mouth + association_class=A` 横向口门已切到 trace-based rule
  - `58163436 -> single_sided_semantic_plus_5m / cut_length_m = 45.417283`
  - `629431331 -> single_sided_semantic_plus_5m / cut_length_m = 22.863822`
- `707476`
  - `accepted / V1`
  - final geometry no longer regrows beyond the `20m` directional boundary
- `709431`
  - `accepted / V1`
  - tracing 无法形成横向 terminal-node pair，三条 selected roads 全部回到 `20m`
- `758888`
  - `accepted / V1`
  - `Step3 two-node T bridge` 已被 `Step67` 继承，不再在横方向截断后出现中心断开或多组件狭长残留
- `851884`
  - `accepted / V1`
  - `Step3 two-node T bridge` 已被 `Step67` 继承，不再在横方向截断后出现中心断开
- `761318 / 765003`
  - `accepted / V1`
  - `two-node T bridge` 继承后，中心桥位保持连通，横方向截断不再留下狭长残留
- `787133`
  - `accepted / V1`
  - degree-2 `RCSDRoad` chain merge prevents same-chain support fragment from being reclassified into `excluded_rcsdroad_ids`

## 7. Remaining Rejected Cases

- `707913`
- `954218`
- `520394575`

Current machine result for all three remains:

- `step7_state = rejected`

Manual review / data governance note:

- The above three cases have been manually confirmed as input data errors in thread evidence.
- This is a closeout governance conclusion, not a new machine-state field.
- Current interpretation:
  - `Step1-7` execution result is considered correct
  - remaining rejection is attributed to input data error, not current algorithm backlog

## 8. Conclusion

- `Step67 clarified formal stage closeout`: **成立**
- `default 58-case run`: **完成**
- `default 58-case correctness baseline`: **成立**
- `Step67 current accepted baseline`: **成立，但仍保留 3 个数据侧异常拒绝案例**
- `少量 accepted case 的几何形状优化`: **保留为后续长期迭代方向，不再构成当前正式准出阻塞项**

解释：

- 当前 T03 正式文档面已经可以把 Step67 视为已正式吸收的 clarified formal stage
- 当前 `58` 个默认正式验收 case 的业务正确性已经满足人工目视审计要求
- solver 常量、几何启发式细调与少量 accepted case 的形状优化，仍保留在长期迭代层，不伪装为新的长期机器契约
- remaining `3` 个数据错误案例的人工处置语义，仍保留在 closeout / thread deliverables 层，不伪装为新的长期机器契约
