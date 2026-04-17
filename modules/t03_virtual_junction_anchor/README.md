# t03_virtual_junction_anchor

> 本文件是 `t03_virtual_junction_anchor` 的操作者入口说明。正式契约以 `INTERFACE_CONTRACT.md` 为准，长期设计以 `architecture/*` 为准。

## 1. 当前定位

- T03 当前只承接 `Phase A / Step3 legal-space baseline only`
- 当前已进入 `Step3` 修复轮，目标是把 baseline 收敛到可验收状态，而不是重做模块骨架
- 正式输入契约固定为 Anchor61 `case-package`
- Anchor61 原始样本仍为 `61` 个 case；其中 `922217 / 54265667 / 502058682` 已确认为 input-gate hard-stop case，默认全量跑批会排除它们，只在显式点名单时单独复跑
- 线程 `REQUIREMENT.md` 本轮整体不启用，不作为当前模块事实源
- 本轮交付：
  - 独立 `Step1/Step2` 最小支撑
  - `Step3 legal space`
  - 批量运行
  - case 级输出
  - 平铺 PNG 审查目录

## 2. 官方入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

## 3. 默认路径

- 默认输入根：`/mnt/e/TestData/POC_Data/T02/Anchor`
- 默认输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a`

## 4. 典型运行方式

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space \
  --case-root /mnt/e/TestData/POC_Data/T02/Anchor \
  --workers 4 \
  --out-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a \
  --run-id t03_phase_a_demo \
  --debug
```

## 5. 当前正式边界

- `Step3` 只输出 `allowed space / negative mask / step3 status`
- 批次级正式交付还包括 `step3_review.png`、`step3_review_flat/`、`step3_review_index.csv`、`summary.json`
- 当前路口关联 branch 上，进入路口与退出路口的 road 都属于可追溯的合法活动链，应双向追到上一个或下一个语义路口
- `Rule A` 只截当前 branch 真正进入相邻语义路口的入口，按相邻路口处 `1m` 逆向掩膜处理，且不能覆盖当前 target core
- `Rule A` 的条带应按局部 road surface 截面生成，不得继续使用脱离局部路面的固定宽条带
- `Rule B / Rule E` 不得把当前路口关联 road 或其二度衔接 road 回灌成 `foreign / opposite`
- `Rule B` 的 `node fallback` 仍是允许的正式边界手段，只保留审计留痕，不自动进入 `review`
- `Rule D` 的 `50m fallback` 在无更早稳定边界时允许直接成立，不自动进入 review，只在 `step3_audit.json` 保留审计信息
- `single_sided_t_mouth` 的方向歧义只在候选方向会导出不同 road partition 时才保留；局部向量并列但 partition 等价时，不再单独升为 `review`
- 双 node `single_sided_t_mouth` 场景下，两 `node` 间 bridge 进入 `allowed-space` 主通路；共享 `2进2出` `node` 若仅承担 through-node，不得中断主通路
- `RCSDRoad` 在 `Rule E` 中只承担 near-corridor proxy，必须挂靠到 opposite `SWSD road`，不能以 opposite side 全量 `RCSDRoad` 主导硬阻断；若 proxy 仍稳定覆盖当前 branch 或 junction-related roads，则必须 suppress
- `Rule E` 当前只到 `single_sided opposite-side guard baseline partial`；当前 opposite-side guard 仅使用 `opposite road / opposite semantic node / near-corridor proxy`，当前 baseline 不单独定义 lane 级对向护栏能力
- 不实现 `Step4/5/6/7`
- 不允许把 `cleanup / trim / review_mode / stage4 聚合` 前置成 `Step3` 成立条件
- 平铺 PNG 审查目录是正式交付物之一
- Anchor 原始样本固定为 `61`；默认正式全量验收统计口径为排除 `922217 / 54265667 / 502058682` 后的 `58` 个 case，并会在 `preflight.json / summary.json` 记录 `excluded_case_ids`

## 6. Patch Round 操作者口径

- 本 README 面向 patch round 操作者，只说明当前轮允许执行的正式口径与默认验收边界，不替代 `INTERFACE_CONTRACT.md`
- patch round 只做增量修补，不覆盖既有契约结论，不回退并行代码修改，不把 `baseline partial` 误写成 fully complete
- 若实现、审计结果与本页或契约面不一致，操作者应先回写审计事实，再由后续 patch round 继续收口
