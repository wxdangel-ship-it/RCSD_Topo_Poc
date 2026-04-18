# t03_virtual_junction_anchor

> 本文件是 `t03_virtual_junction_anchor` 的操作者入口说明。正式契约以 `INTERFACE_CONTRACT.md` 为准，长期设计以 `architecture/*` 为准。

## 1. 当前定位

- T03 当前正式承接“冻结 `Step3 legal-space baseline` 之上的 `Step4-5` 联合阶段”
- `Step3` 仍是冻结前置层；当前工作重点是治理文档同步、契约收口、测试补强与进入 `Step6` 前的轻量整备
- 正式输入契约固定为 Anchor61 `case-package`
- Anchor61 原始样本仍为 `61` 个 case；其中 `922217 / 54265667 / 502058682` 已确认为 input-gate hard-stop case，默认全量跑批会排除它们，只在显式点名单时单独复跑
- 当前正式交付：
  - `Step4 = RCSD` 关联语义识别
  - `Step5 = foreign` 过滤与排除落地
  - 单 case / batch 输出
  - `step45_review_flat/` 平铺 PNG 审查目录

## 2. 官方入口

```bash
python3 -m rcsd_topo_poc t03-step45-rcsd-association --help
```

## 3. 冻结前置入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

## 4. 默认路径

- 默认输入根：`/mnt/e/TestData/POC_Data/T02/Anchor`
- 默认 `Step3` 前置根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003`
- 默认 `Step4-5` 输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step45_joint_phase`

## 5. 典型运行方式

```bash
python3 -m rcsd_topo_poc t03-step45-rcsd-association \
  --step3-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003 \
  --workers 4 \
  --out-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step45_joint_phase \
  --run-id t03_step45_demo \
  --debug
```

## 6. 当前正式边界

- `Step4-5` 必须消费冻结 `Step3 allowed space / step3_status / step3_audit`
- 当前正式模板只包括 `center_junction / single_sided_t_mouth`
- 正式交付是 `required / support / excluded` RCSD 中间结果包、hook zone、foreign context、状态/审计、PNG 与批量汇总
- `association_class` 契约只允许 `A / B / C`
- `step45_state` 契约只允许 `established / review / not_established`
- `B / review` 是当前正式保守策略，不视为算法缺陷；其含义是“已有 support / hook zone，但 RCSD semantic core 仍待 `Step6` 收窄”
- `degree = 2` 的 `RCSDNode` 不进入 `required semantic core`
- 每个 case 只处理当前 SWSD 路口所在道路面；道路面外的 SWSD / RCSD 对象不进入当前 case 全局处理
- `single_sided_t_mouth` 的平行重复 `support RCSDRoad` 按竖方向退出当前面一侧去重
- 本模块当前不进入 `Step6/7`
- 不允许把 `cleanup / trim`、`review_mode` 或其它补救链前置成 `Step4-5` 成立条件
- 平铺 PNG 审查目录与 `preflight.json / summary.json / step45_review_index.csv` 是正式交付物之一
- Anchor 原始样本固定为 `61`；默认正式全量验收统计口径为排除 `922217 / 54265667 / 502058682` 后的 `58` 个 case，并会在 `preflight.json / summary.json` 记录 `excluded_case_ids`
- 未传 `--case-id` 时，默认正式验收集按上述 `58` 个 case 运行；显式传入 `--case-id` 时，不应用默认排除集
- `preflight.json / summary.json` closeout 时至少应直接看到：
  - `raw_case_count`
  - `default_formal_case_count`
  - `excluded_case_ids`
  - `effective_case_ids`
- Step3 baseline closeout 证据见：`modules/t03_virtual_junction_anchor/architecture/04-step3-closeout.md`
- Step4-5 联合阶段 closeout 证据见：`modules/t03_virtual_junction_anchor/architecture/06-step45-closeout.md`

## 7. Patch Round 操作者口径

- 本 README 面向 patch round 操作者，只说明当前轮允许执行的正式口径与默认验收边界，不替代 `INTERFACE_CONTRACT.md`
- patch round 只做增量修补、契约收口、测试补强与轻量整备，不覆盖既有契约结论，不回退并行代码修改，不把 review guard 误写成 fully complete
- 若实现、审计结果与本页或契约面不一致，操作者应先回写审计事实，再由后续 patch round 继续收口
