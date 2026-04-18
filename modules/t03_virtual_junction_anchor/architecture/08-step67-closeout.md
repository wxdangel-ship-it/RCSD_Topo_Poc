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

- current formal run root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step67_phase/20260418_t03_step67_formal_v008`
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
- `degree = 2` connector `RCSDNode` itself does not become semantic core; its connected candidate `RCSDRoad` chain is merged upstream before `required / support / excluded` classification

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

- run_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step67_phase/20260418_t03_step67_formal_v008`
- case_dir_count: `58`
- flat_png_count: `58`
- missing_case_ids: `[]`
- failed_case_ids: `[]`
- Step7 result distribution:
  - `accepted = 55`
  - `rejected = 3`
- visual distribution:
  - `V1 = 50`
  - `V2 = 5`
  - `V4 = 3`
  - `V5 = 0`

Reference files:

- `outputs/_work/t03_step67_phase/20260418_t03_step67_formal_v008/preflight.json`
- `outputs/_work/t03_step67_phase/20260418_t03_step67_formal_v008/summary.json`
- `outputs/_work/t03_step67_phase/20260418_t03_step67_formal_v008/step67_review_index.csv`

## 6. Representative Recoveries

- `698330`
  - `accepted / V1`
  - selected-road longitudinal segment no longer gets incorrectly shortened by foreign handling
- `706389`
  - `accepted / V1`
  - no longer rejected by node-based foreign interpretation
- `707476`
  - `accepted / V1`
  - no longer rejected by node-based foreign interpretation
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
- `Step67 current accepted baseline`: **成立，但仍保留 3 个数据侧异常拒绝案例**

解释：

- 当前 T03 正式文档面已经可以把 Step67 视为已正式吸收的 clarified formal stage
- 但 solver 常量、几何启发式和 remaining 3 个数据错误案例的人工处置语义，仍保留在 closeout / thread deliverables 层，不伪装为新的长期机器契约
