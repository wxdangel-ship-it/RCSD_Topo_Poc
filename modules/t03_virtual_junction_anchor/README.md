# t03_virtual_junction_anchor

> 本文件是 `t03_virtual_junction_anchor` 的操作者入口说明。正式契约以 `INTERFACE_CONTRACT.md` 为准，长期设计以 `architecture/*` 为准。

## 1. 当前定位

- T03 当前正式承接“冻结 `Step3 legal-space baseline` 之上的 `Step4-7 clarified formal stage`”
- `Step3` 仍是冻结前置层；当前正式模板只包括 `center_junction / single_sided_t_mouth`
- 正式输入契约固定为 Anchor61 `case-package`
- Anchor61 原始样本仍为 `61` 个 case；其中 `922217 / 54265667 / 502058682` 已确认为 input-gate hard-stop case，默认全量跑批会排除它们，只在显式点名单时单独复跑
- 当前正式交付包括：
  - `Step4-5 = RCSD` 关联语义识别与 `required / support / excluded` 中间结果包
  - `Step6 =` 受约束几何建立与审计
  - `Step7 = accepted / rejected` 最终发布
  - 单 case / batch 输出
  - `step45_review_flat/`、`step67_review_flat/` 与索引汇总

## 2. 官方入口

```bash
python3 -m rcsd_topo_poc t03-step45-rcsd-association --help
```

说明：

- 当前 repo 官方 CLI 仍只有 `Step4-5` 联合阶段入口。
- 本轮未新增 `Step67` 官方 CLI；`Step67` 正式交付由模块内 batch runner 与 closeout 维持。

## 3. 冻结前置入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

## 4. 当前 Step67 交付方式

- 当前 `Step67` 的正式批量交付通过模块内 `run_t03_step67_batch()` 生成。
- 这属于当前模块的正式交付面，但不是 repo 官方入口，不登记到 `entrypoint-registry.md`。

## 5. 默认路径

- 默认输入根：`/mnt/e/TestData/POC_Data/T02/Anchor`
- 默认 `Step3` 前置根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003`
- 默认 `Step4-5` 输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step45_joint_phase`
- 默认 `Step67` 输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step67_phase`

## 6. 当前正式边界

- `Step4-7` 必须消费冻结 `Step3 allowed space / step3_status / step3_audit`
- `association_class` 契约只允许 `A / B / C`
- `step45_state` 契约只允许 `established / review / not_established`
- `step7_state` 契约只允许 `accepted / rejected`
- `B / review` 是当前正式保守策略，不视为算法缺陷；其含义是“已有 support / hook zone，但 RCSD semantic core 仍待 `Step6` 收窄”
- `support_only` 在 `Step6` 合法收敛后允许转为 `Step7 accepted`
- `degree = 2` 的 `RCSDNode` 不进入 `required semantic core`；经其串接的 candidate `RCSDRoad` 必须先按 chain 合并，再参与 `required / support / excluded` 分类
- 每个 case 只处理当前 SWSD 路口所在道路面；道路面外的 SWSD / RCSD 对象不进入当前 case 主结果集合
- `single_sided_t_mouth` 的平行重复 `support RCSDRoad` 继续按竖方向退出当前面一侧去重
- `Step6` 是受约束几何层，不是 cleanup 驱动补救层
- `Step7` 只负责最终业务发布，不重新定义 `required / support / excluded / foreign`
- `V1-V5` 只属于视觉审计层，不等价于主机器状态
- `Step5` 当前不再生成 hard foreign polygon context；`Step6` hard negative mask 仅消费 road-like `1m` mask
- `step45_foreign_swsd_context.gpkg / step45_foreign_rcsd_context.gpkg` 当前仅作为兼容性审计产物保留，可以为空
- Anchor 原始样本固定为 `61`；默认正式全量验收统计口径为排除 `922217 / 54265667 / 502058682` 后的 `58` 个 case，并会在 `preflight.json / summary.json` 记录 `excluded_case_ids`
- 未传 `--case-id` 时，默认正式验收集按上述 `58` 个 case 运行；显式传入 `--case-id` 时，不应用默认排除集

## 7. 当前 closeout 与历史文档

- Step3 baseline closeout：`modules/t03_virtual_junction_anchor/architecture/04-step3-closeout.md`
- Step4-5 joint phase closeout：`modules/t03_virtual_junction_anchor/architecture/06-step45-closeout.md`
- Step67 clarified formal stage closeout：`modules/t03_virtual_junction_anchor/architecture/08-step67-closeout.md`
- `07-step6-readiness-prep.md` 保留为 Step67 正式落地前的历史准备文档，不再定义当前正式范围

## 8. Patch Round 操作者口径

- 本 README 面向 patch round 操作者，只说明当前轮允许执行的正式口径与默认验收边界，不替代 `INTERFACE_CONTRACT.md`
- patch round 只做增量修补、契约收口、测试补强与 closeout 同步，不顺手扩大为新的执行入口治理轮次
- 若实现、审计结果与本页或契约面不一致，操作者应先回写审计事实，再由后续 patch round 继续收口
