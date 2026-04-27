# T03 / Step4-5 Joint Phase Closeout

## 1. Scope

- scope: `T03 / Step4-5` joint phase on top of frozen `Step3`
- templates:
  - `center_junction`
  - `single_sided_t_mouth`
- non-goals:
  - `diverge / merge / continuous divmerge / complex 128`
  - rewriting `Step3 allowed space / corridor / 50m fallback`
  - polygon finalization

本文件用于在 `_work` 运行结果不提交入库时，保留 Step4-5 联合阶段的 closeout 证据摘要。当前 Step4-5 已作为 Finalization clarified formal stage 的冻结前置层保留。

## 2. Closeout Run

- run_id: `20260418_t03_association_phase_v004`
- command:

```bash
PYTHONPATH=src python3 -m rcsd_topo_poc t03-rcsd-association \
  --step3-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003 \
  --out-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_association_phase \
  --run-id 20260418_t03_association_phase_v004 \
  --workers 4
```

- environment:
  - runtime: `WSL2`
  - python: `/usr/bin/python3`
  - case_root: `/mnt/e/TestData/POC_Data/T02/Anchor`
  - step3_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003`
  - out_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_association_phase`

## 3. Formal Acceptance Scope

- raw_case_count: `61`
- default_formal_case_count: `58`
- excluded_case_ids:
  - `922217`
  - `54265667`
  - `502058682`
- effective acceptance rule:
  - 默认未传 `--case-id` 时，正式全量验收按排除上述 `3` 个 case 后的 `58` 个 case 运行
  - 显式传入 `--case-id` 时，不应用默认排除集，但前提是指定 `step3_root` 中存在对应 Step3 产物

## 4. Batch Result

- run_root: `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_association_phase/20260418_t03_association_phase_v004`
- case_dir_count: `58`
- flat_png_count: `58`
- flat_subdir_count: `0`
- tri_state_sum: `58`
- tri_state distribution:
  - `established = 28`
  - `review = 30`
  - `not_established = 0`
- missing_case_ids: `[]`
- failed_case_ids: `[]`
- association / reason distribution:
  - `association_established = 25`
  - `association_support_only = 30`
  - `association_no_related_rcsd = 3`
- template / state distribution:
  - `center_junction / established = 13`
  - `center_junction / review = 13`
  - `single_sided_t_mouth / established = 15`
  - `single_sided_t_mouth / review = 17`

Reference files:
- `outputs/_work/t03_association_phase/20260418_t03_association_phase_v004/preflight.json`
- `outputs/_work/t03_association_phase/20260418_t03_association_phase_v004/summary.json`
- `outputs/_work/t03_association_phase/20260418_t03_association_phase_v004/association_review_index.csv`

## 5. Representative Cases

- `10970944`
  - `center_junction`
  - `association_class = A`
  - `association_state = established`
  - `reason = association_established`
- `520394575`
  - `single_sided_t_mouth`
  - `association_class = A`
  - `association_state = established`
  - `reason = association_established`
- `584141`
  - `center_junction`
  - `association_class = B`
  - `association_state = review`
  - `reason = association_support_only`
- `1213535`
  - `single_sided_t_mouth`
  - `association_class = B`
  - `association_state = review`
  - `reason = association_support_only`
- `698418`
  - `center_junction`
  - `association_class = C`
  - `association_state = established`
  - `reason = association_no_related_rcsd`

## 6. Capability Declaration

- `Step4`
  - 只在冻结 `Step3 allowed space` 内收集 RCSD 候选
  - 只处理当前 SWSD 路口所在道路面上的 SWSD / RCSD 对象；道路面外对象不参与当前 case 全局处理
  - 输出严格收敛到契约枚举 `A / B / C` 的关联分类
  - `B` 类以 hook zone 裁剪片段为主，不退化为整条 RCSDRoad 全段
  - 对 `single_sided_t_mouth` 的平行重复 `support RCSDRoad`，按竖方向退出当前面一侧做去重，避免把仅平行贴近的 RCSDRoad 一并保留
  - `association_support_only` 明确表示“RCSD 下没有稳定语义路口 core”，因此当前阶段保守记为 `review`，并显式落 `rcsd_semantic_core_missing = true`
  - `degree = 2` 的 `RCSDNode` 不进入 `required semantic core`；这类 local connector node 在审计中与真正 foreign node 分桶记录
  - `association_class` 不再输出 `unsupported / blocked`；门禁失败统一通过 `association_blocker / association_prerequisite_issues` 表达
- `Step5`
  - 将 `excluded RC` 直接视为 `foreign RC`
  - `foreign_swsd_context` 也只保留当前 SWSD 道路面上的局部对象
  - 输出 `foreign SWSD context` 与 `foreign RCSD context`
  - 为 `Step6` 提供硬边界与中间结果包，而不是 polygon
  - `association_audit.json` 额外记录 `ignored_outside_current_swsd_surface_*`，用于审计哪些对象因不在当前道路面而被整体忽略
  - 冻结 Step3 prerequisite 改为显式校验：`selected_road_ids` 缺失时不再回退到 `Step1 target_road_ids`
- Render / batch
  - 复用 Step3 三态样式
  - 平铺 `association_review_flat/`，目录内无子目录
  - `summary.json / preflight.json / association_review_index.csv` 全部稳定落盘
  - `preflight.json` 在运行结束后回填 `excluded_case_ids / effective_case_ids / missing_case_ids / failed_case_ids`

## 7. Conclusion

- `Step4-5 joint phase closeout`: **成立**
- `default 58-case run`: **完成**
- `Finalization 冻结前置 baseline`: **成立**

解释：
- `28` 个 case 已达 `established`
- `30` 个 case 为 `review`，全部来自 `association_class = B / reason = association_support_only`
- 上述 `30` 个 `review` 是当前正式业务策略，不视为算法缺陷；它们统一表示“已有 support/hook zone，但 RCSD 语义 core 仍待 `Step6` 收窄”
- 当前没有 `not_established`，说明本轮实现已经形成稳定可交付的联合阶段中间结果包
- 该结论作为 `Finalization clarified formal stage` 的历史前置 closeout 保留；当前正式 Finalization closeout 见 `history/step6-step7-finalization-closeout.md`

## 8. Non-Blocking Residuals

- `review` case 仍需人工复核 support-only hook zone 是否足以支撑后续 Step6
- `association_audit.json` 已将 `nonsemantic_connector_rcsdnode_ids` 与 `true_foreign_rcsdnode_ids` 分开，供 `Step6` 继续精化
- 当前默认 `--step3-root` 绑定到现行官方 Step3 baseline run root；若更换 Step3 基线，需要同步调整 closeout 与默认参数
- 当前 `association_class = B` 统一映射到 `review`，后续若业务拍板“support-only 也可直通 Step6”，需要另行调整状态口径
