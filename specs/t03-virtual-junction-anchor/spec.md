# T03 / Phase A - Step3 Legal-Space Baseline

## 1. 文档定位

- 文档类型：spec-kit 变更工件
- 状态：`active change / phase-a`
- 本文件服务于 `t03_virtual_junction_anchor` 的 Phase A 启动，不替代模块长期真相。
- 当前任务已进入 `Step3` 修复轮，本文件只追加修复说明，不重写总体业务。

## 2. 本轮目标

- 在独立模块 `t03_virtual_junction_anchor` 中，以 Anchor61 `case-package` 为正式输入契约，实现最小 `Step1/Step2` 支撑与完整 `Step3 legal space`。
- 支持 `61` 个 case 的批量运行、case 级输出、平铺 PNG 审查目录、索引与汇总。
- 将 T03 固化为“只做到 Step3 的干净新基线”，为后续 `Step4-7` 留扩展位。
- 本轮修复闭环聚焦 `Rule D / Rule E / Rule F / Rule G` 与 Anchor61 真实验收，不引入 `Step4-7` 语义。
- `Rule D` 的最终 `allowed space` 必须满足 `DriveZone` containment；当不存在更早的稳定边界时，`50m fallback` 允许作为可成立路径，不自动进入 `review`，但必须保留 fallback 审计信息

## 3. 正式输入契约

- 本轮正式输入固定为 `/mnt/e/TestData/POC_Data/T02/Anchor/<case_id>/` 下的 `case-package`：
  - `manifest.json`
  - `size_report.json`
  - `drivezone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`
- 线程 `REQUIREMENT.md` 本轮整体不启用；其中旧的 `lane_centerline.json / lane_topology.json` 输入口径视为历史误写，不进入本轮事实源。
- 所有空间处理统一在 `EPSG:3857`。

## 4. Step3 正式范围

- `Step1`：只负责组装 `semantic_junction_set`、must-cover group nodes、本地 `roads / RC roads / RC nodes` 视图。
- `Step2`：只负责模板归类：
  - `kind_2 = 4 -> center_junction`
  - `kind_2 = 2048 -> single_sided_t_mouth`
- `Step3`：只负责冻结合法活动空间，输出 `allowed space / negative mask / step3 status`。

## 5. Step3 A-H 冻结规则

- A：相邻语义路口入口截断；只对当前语义路口 branch 上真正进入相邻语义路口的 road 生效。在与当前路口直接关联的相邻语义路口入口处，沿当前 branch 反向构造 `1m` 逆向掩膜，正向增长到这里应自然终止；不再依赖路口前横截切面。若候选截断会覆盖当前 target group core，则该截断无效。
- B：同面无关对象负向掩膜；优先对 `foreign road / arm` 做 `1m` 缓冲，无法识别时退化为 node 小范围掩膜；当前语义路口 branch、直接关联 road 及其二度衔接 road 不得因“未进入 frontier”而被回灌为 foreign。
- C：其他语义路口内部 node 的 MST 负向掩膜；MST 连线只保留道路面内部分，并做 `1m` 缓冲。
- D：候选空间只能在 `DriveZone` 内沿合法方向增长，不得越过负向掩膜或非道路面；在当前语义路口关联 branch 上，进入路口与退出路口的 road 都属于可追溯的合法活动链，应双向追溯到下一个或上一个语义路口；最终 `allowed space` 必须回切 `DriveZone`；无更早稳定边界时，单向最大增长距离 `50m`，且该 fallback 允许直接成立，不自动提升为 `review`，只在审计中留痕。
- E：`single_sided_t_mouth` 当前定义为 baseline partial，`lane_guard_status=proxy_only_not_modeled`；不得进入对向 `Road / semantic Node / lane / main corridor`；但当前语义路口关联 road 及其二度衔接 road 不得被误判为 opposite。`RCSDRoad` 只能在 opposite `SWSD road` 证据不足或偏出路面时，作为 near-corridor proxy 补充，不得按 opposite side 全量 `RCSDRoad` 直接主导硬阻断；若某个 `RCSDRoad` proxy 仍稳定覆盖当前 branch 或 junction-related roads，则必须 suppress，不得写入 `opposite_corridor_buffer`。对双 node `single_sided_t_mouth`，两 `node` 间 bridge 进入 `allowed-space` 主通路；共享 `2进2出` `node` 作为 through-node 时不应中断主通路增长。
- F：若某个 case 只能依赖 `cleanup / trim` 才满足边界，则 `Step3` 未成立。
- G：任何放大都只能在 `A-F` 满足后进行，不得先放大再补救越界。
- H：旧 `10m` 正式口径取消，统一采用“无更早边界时单向 `50m`”。

## 6. 输出契约

- 单 case 固定输出：
  - `step3_allowed_space.gpkg`
  - `step3_negative_mask_adjacent_junction.gpkg`
  - `step3_negative_mask_foreign_objects.gpkg`
  - `step3_negative_mask_foreign_mst.gpkg`
  - `step3_status.json`
  - `step3_audit.json`
  - `step3_review.png`
- 批次固定输出：
  - `preflight.json`
  - `summary.json`
  - `step3_review_index.csv`
  - `step3_review_flat/`
  - `cases/`
- `step3_review_flat/` 必须平铺所有 case PNG，目录内禁止出现子目录。

## 7. 状态与审查

- `step3_state` 只允许：
  - `established`
  - `review`
  - `not_established`
- `input_gate_failed` 作为前置输入门禁 `reason` 允许出现，但不新增第四种 `step3_state`，也不替代 Step3 业务状态
- 已确认的 input-gate hard-stop case `922217 / 54265667 / 502058682` 记录为默认全量验收排除集：后续默认全量跑批不再把这 `3` 个 case 计入测试用例级统计，但显式点名单 case 调试仍允许单独运行
- `Step4/5/6/7` 不在本轮范围内；不得用它们的语义或补救逻辑反向证明 `Step3` 成立。
- T02 的 `late_*cleanup* / trim / review_mode / stage4 聚合` 本轮禁止前置进入 T03。
- `Rule D` 的 `outside_drivezone` 失败优先级高于普通 review signal；若最终 `allowed space` 越出 `DriveZone` 超阈值，case 不得仅作为普通 `review` 保留。
- `Rule D` 的 `50m fallback` 若被使用，不单独构成 review signal；必须在 `step3_audit.json` 明确记录 fallback 原因、距离与是否启用。
- `Rule E` 当前只承诺 baseline partial；`lane_guard_status=proxy_only_not_modeled` 属于建议落盘字段，不得在文档或验收陈述中表述为 fully complete。
- 对双 node `single_sided_t_mouth` 建议补充审计字段：`double_node_bridge_in_allowed_space / through_node_shared_2in2out / through_node_break_suppressed`

## 8. 验证

- CLI 帮助可用：`python3 -m rcsd_topo_poc t03-step3-legal-space --help`
- 至少补齐 CLI、loader、writer、state mapping、rule-level 修复测试与 run 级 summary 回读。
- Anchor61 原始 Anchor 总量仍为 `61`，默认正式全量验收集按排除 `922217 / 54265667 / 502058682` 后的 `58` 个 case 统计；显式点名单 case 不受该默认排除影响
- 必须真实跑完默认全量验收集，核对：
  - `cases/` 有 `58` 个 case 目录
  - `step3_review_flat/` 有 `58` 张 PNG 且无子目录
  - `step3_review_index.csv` 与 `summary.json` 字段完整
  - 三态计数之和等于 `58`
  - `excluded_case_ids == ["922217", "54265667", "502058682"]`
  - `missing_case_ids == []`
  - `failed_case_ids == []`

## 9. 非目标

- 不实现 `Step4/5/6/7`
- 不修改 T02 正式业务结果
- 不把 `outputs/_work`、批量 PNG、线程同步文件提交进 Git
