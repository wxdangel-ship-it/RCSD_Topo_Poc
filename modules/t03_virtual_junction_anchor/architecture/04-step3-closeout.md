# T03 / Phase A / Step3 Baseline Closeout

## 1. Scope

- branch: `codex/t03-phasea-step3-legal-space`
- scope: `T03 / Phase A / Step3` only
- non-goals:
  - `Step4/5/6/7`
  - cleanup/trim as a Step3 establishment path
  - lane-level opposite-side guard completion

本文件是当前 Step3 baseline 的轻量 closeout 证据摘要，用于在 `_work` 结果不提交入库时，仍能在仓库内复核当前基线是如何封板的。

## 2. Closeout Run

- run_id: `20260418_t03_step3_closeout_v002`
- command:

```bash
PYTHONPATH=src python3 -m rcsd_topo_poc t03-step3-legal-space \
  --case-root /mnt/e/TestData/POC_Data/T02/Anchor \
  --workers 4 \
  --out-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a \
  --run-id 20260418_t03_step3_closeout_v002
```

- environment:
  - runtime: `WSL2`
  - python: `/usr/bin/python3`
  - python_version: `3.10.12`
  - platform: `Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.35`
  - case_root: `/mnt/e/TestData/POC_Data/T02/Anchor`
  - out_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a`

## 3. Formal Acceptance Scope

- raw_case_count: `61`
- default_formal_case_count: `58`
- excluded_case_ids:
  - `922217`
  - `54265667`
  - `502058682`
- effective acceptance rule:
  - 默认未传 `--case-id` 时，正式全量验收按排除上述 3 个 hard-stop case 后的 `58` 个 case 运行
  - 显式传入 `--case-id` 时，不应用默认排除集，仍可单独复跑这些 case

## 4. Batch Result

- run_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_closeout_v002`
- case_dir_count: `58`
- flat_png_count: `58`
- flat_subdir_count: `0`
- tri_state_sum: `58`
- tri_state distribution:
  - `established = 58`
  - `review = 0`
  - `not_established = 0`
- missing_case_ids: `[]`
- failed_case_ids: `[]`

Reference files:
- `outputs/_work/t03_step3_phase_a/20260418_t03_step3_closeout_v002/preflight.json`
- `outputs/_work/t03_step3_phase_a/20260418_t03_step3_closeout_v002/summary.json`
- `outputs/_work/t03_step3_phase_a/20260418_t03_step3_closeout_v002/step3_review_index.csv`

## 5. Capability Declaration

- `Rule D`
  - `direction_mode = t02_direction_plus_bidirectional_junction_trace`
  - `50m fallback` 允许成立，只在审计中留痕，不自动提升为 `review`
  - `single_sided_t_mouth` 的方向判定优先采用语义横方向：若识别出一组 `1` 条进入 + `1` 条退出、轴线近似共线、且远离路口后几何距离持续发散的 direct roads，则应以该组 road 确定横方向主轴；局部分数只作为 fallback
- `Rule A`
  - adjacent cut 若会覆盖当前 target core，则被 suppress
  - audit 中保留 materialized / suppressed cut 与 suppress reason
- `Rule E`
  - 当前正式口径为 `single_sided opposite-side guard baseline partial`
  - 当前 opposite-side guard 只承诺：
    - `opposite road`
    - `opposite semantic node`
    - `near-corridor proxy`
  - 当前 baseline 不单独定义 lane 级对向护栏能力
- 双 node `single_sided_t_mouth`
  - bridge 已进入 `allowed-space` 主通路
  - shared `2-in-2-out` node 可作为 through-node，不中断 tracing/frontier

## 6. Conclusion

- `Step3 baseline closeout`: **成立**
- `可作为 Step4 前置基线`: **成立**

解释：
- 当前 Step3 baseline 已完成默认正式 `58-case` 验收口径的代码、输出、审计字段与文字证据闭环
- 当前默认正式 `58-case` 验收集已全部收敛为 `established`
- 当前 `Rule E` 仍为 baseline partial，这属于已声明的非阻塞残留项，不影响本轮把 Step3 作为 Step4 的稳定输入前提

## 7. Non-Blocking Residuals

- `Rule E` 仍为 baseline partial，不宣称 lane-level opposite-side guard completion
- `single_sided_t_mouth` 的方向语义已按“横方向主轴优先、局部分数 fallback”收口；后续若继续演化，应在此语义边界内推进，而不是回退到纯分数竞争
