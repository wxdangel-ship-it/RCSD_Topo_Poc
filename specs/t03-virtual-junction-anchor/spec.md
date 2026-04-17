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
- `Rule D` 的最终 `allowed space` 必须满足 `DriveZone` containment；若 `allowed_outside_drivezone_area_m2` 超过稳定阈值，则 `Rule D` 失败，case 不能只作为普通 `review`

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

- A：相邻语义路口入口截断；只对当前语义路口 branch 上真正进入相邻语义路口的 road 生效，沿进入相邻语义路口的道路方向，在入口边界前 `1m` 设置垂直负向边界，并应覆盖该处局部 road surface 截面；若候选截断会覆盖当前 target group core，则该截断无效，不得退化成脱离局部路面的固定宽条带。
- B：同面无关对象负向掩膜；优先对 `foreign road / arm` 做 `1m` 缓冲，无法识别时退化为 node 小范围掩膜；当前语义路口 branch、直接关联 road 及其二度衔接 road 不得因“未进入 frontier”而被回灌为 foreign。
- C：其他语义路口内部 node 的 MST 负向掩膜；MST 连线只保留道路面内部分，并做 `1m` 缓冲。
- D：候选空间只能在 `DriveZone` 内沿合法方向增长，不得越过负向掩膜或非道路面；在当前语义路口关联 branch 上，进入路口与退出路口的 road 都属于可追溯的合法活动链，应双向追溯到下一个或上一个语义路口；最终 `allowed space` 必须回切 `DriveZone`，且 `allowed_outside_drivezone_area_m2` 超阈值时判失败；无更早边界时单向最大增长距离 `50m`。
- E：`single_sided_t_mouth` 不得进入对向 `Road / semantic Node / lane / main corridor`；但当前语义路口关联 road 及其二度衔接 road 不得被误判为 opposite。`RCSDRoad` 只能在 opposite `SWSD road` 证据不足或偏出路面时，作为 near-corridor proxy 补充，不得按 opposite side 全量 `RCSDRoad` 直接主导硬阻断。
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
- `Step4/5/6/7` 不在本轮范围内；不得用它们的语义或补救逻辑反向证明 `Step3` 成立。
- T02 的 `late_*cleanup* / trim / review_mode / stage4 聚合` 本轮禁止前置进入 T03。
- `Rule D` 的 `outside_drivezone` 失败优先级高于普通 review signal；若最终 `allowed space` 越出 `DriveZone` 超阈值，case 不得仅作为普通 `review` 保留。

## 8. 验证

- CLI 帮助可用：`python3 -m rcsd_topo_poc t03-step3-legal-space --help`
- 至少补齐 CLI、loader、writer、state mapping、rule-level 修复测试与 run 级 summary 回读。
- 必须真实跑完 `61` 个 case，核对：
  - `cases/` 有 `61` 个 case 目录
  - `step3_review_flat/` 有 `61` 张 PNG 且无子目录
  - `step3_review_index.csv` 与 `summary.json` 字段完整
  - 三态计数之和等于 `61`
  - `missing_case_ids == []`
  - `failed_case_ids == []`

## 9. 非目标

- 不实现 `Step4/5/6/7`
- 不修改 T02 正式业务结果
- 不把 `outputs/_work`、批量 PNG、线程同步文件提交进 Git
