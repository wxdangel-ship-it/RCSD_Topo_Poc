# t03_virtual_junction_anchor

> 本文件是 `t03_virtual_junction_anchor` 的操作者入口说明。正式契约以 `INTERFACE_CONTRACT.md` 为准，业务步骤与实现阶段映射见 `architecture/11-business-steps-vs-implementation-stages.md`。

## 1. 模块定位

T03 面向当前语义路口，在冻结的合法活动空间内识别 RCSD 有效关联关系，构造受约束的最终路口面，并输出正式结果、复核结果与批量执行成果。

正式业务主链按 `Step1~Step7` 表达：

| 步骤 | 业务职责 |
|---|---|
| `Step1` | 当前 case 受理、代表节点与局部上下文建立 |
| `Step2` | 模板归类 |
| `Step3` | 合法活动空间冻结 |
| `Step4` | RCSD 关联语义识别 |
| `Step5` | foreign / excluded 负向约束 |
| `Step6` | 受约束几何生成 |
| `Step7` | 最终验收与发布 |

`Step45` 与 `Step67` 是历史实现阶段和兼容命名，不再作为正式需求主结构。

## 2. 当前正式支持范围

- 当前正式模板：
  - `center_junction`
  - `single_sided_t_mouth`
- Anchor61 原始样本为 `61` 个 case；`922217 / 54265667 / 502058682` 已确认为 input-gate hard-stop case。
- 默认正式全量验收集为排除上述 3 个 input-gate case 后的 `58` 个 case；显式传入 `--case-id` 时仍可单独复跑。
- 不纳入当前 T03 正式范围：
  - `diverge / merge / continuous divmerge / complex 128`
  - 环岛
  - 概率化排序、置信度学习、自动回捞
  - 重写 T02 或 T03 Step3 的冻结规则

## 3. 当前入口

### 3.1 RCSD 关联阶段 CLI

```bash
.venv/bin/python -m rcsd_topo_poc t03-step45-rcsd-association --help
```

该 CLI 名称保留历史 `step45` 命名；当前业务含义对应 `Step4 + Step5`，不表示正式需求主结构仍以 `Step45` 组织。

### 3.2 合法空间冻结前置入口

```bash
.venv/bin/python -m rcsd_topo_poc t03-step3-legal-space --help
```

`Step3` 是当前 T03 正式主链中的合法空间冻结步骤，也是后续 `Step4~Step7` 不得反向篡改的前置事实。

### 3.3 internal full-input 脚本

```bash
OUT_ROOT=/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_internal_full_input \
RUN_ID=t03_innernet_full_$(date +%Y%m%d_%H%M%S) \
./scripts/t03_run_internal_full_input_innernet.sh
```

常用监控：

```bash
./scripts/t03_watch_internal_full_input_innernet.sh
```

主脚本事实：

- `scripts/t03_run_internal_full_input_8workers.sh` 是 T03 internal full-input 主运行脚本。
- `scripts/t03_watch_internal_full_input.sh` 是对应主监控脚本。
- `scripts/t03_run_step67_internal_full_input_8workers.sh` 与 `scripts/t03_watch_step67_internal_full_input.sh` 只保留为历史兼容 wrapper。
- 本轮不新增 repo 官方 CLI，不改变入口签名。

## 4. 主要输出

### 4.1 case 级正式输出

- `step3_allowed_space.gpkg`
- `step3_status.json`
- `step3_audit.json`
- `step45_required_rcsdnode.gpkg`
- `step45_required_rcsdroad.gpkg`
- `step45_support_rcsdnode.gpkg`
- `step45_support_rcsdroad.gpkg`
- `step45_excluded_rcsdnode.gpkg`
- `step45_excluded_rcsdroad.gpkg`
- `step45_status.json`
- `step45_audit.json`
- `step6_polygon_seed.gpkg`
- `step6_polygon_final.gpkg`
- `step6_constraint_foreign_mask.gpkg`
- `step6_status.json`
- `step6_audit.json`
- `step67_final_polygon.gpkg`
- `step7_status.json`
- `step7_audit.json`

说明：`step45_*` 与 `step67_*` 是当前输出兼容文件名，本轮不重命名。

### 4.2 review-only 输出

- `step45_review.png`
- `step67_review.png`
- `t03_review_index.csv`
- `t03_review_summary.json`
- `t03_review_flat/`
- `t03_review_accepted/`
- `t03_review_rejected/`
- `t03_review_v2_risk/`
- `visual_checks/`

`V1~V5` 只属于人工复核层，不等价于机器正式状态。

### 4.3 batch / full-input 正式成果

- `preflight.json`
- `summary.json`
- `virtual_intersection_polygons.gpkg`
- `nodes.gpkg`
- `nodes_anchor_update_audit.csv`
- `nodes_anchor_update_audit.json`
- `_internal/<RUN_ID>/terminal_case_records/<case_id>.json`

`nodes.gpkg` 只更新当前批次代表 node 的 `is_anchor`：

- `accepted -> yes`
- `rejected / runtime_failed -> fail3`

`fail3` 只属于 T03 downstream output 语义，不回写输入原始 `nodes.gpkg`，也不反向修改 T02 上游契约。

## 5. 当前正式边界

- 所有空间处理统一使用 `EPSG:3857`。
- `Step4~Step7` 必须消费冻结 `Step3 allowed space / step3_status / step3_audit`。
- `association_class` 只允许 `A / B / C`。
- `step45_state` 只允许 `established / review / not_established`，这是当前兼容状态字段名。
- `step7_state` 只允许 `accepted / rejected`。
- `B / review` 是当前正式保守策略，不视为算法缺陷；其含义是“已有 support / hook zone，但 RCSD semantic core 仍不足以直接判定主关联”。
- `support_only` 在 `Step6` 合法收敛后允许转为 `Step7 accepted`。
- `degree = 2` 的 `RCSDNode` 不进入 required semantic core；经其串接的 candidate `RCSDRoad` 必须先按 chain 合并，再参与 `required / support / excluded` 分类。
- 当前 case 只处理当前 SWSD 路口所在道路面；道路面外的 SWSD / RCSD 对象不进入当前 case 主结果集合。
- `Step6` 是受约束几何层，不是 cleanup 驱动补救层。
- `Step6` 必须先确定 directional boundary，再在 boundary 内构面；不允许“先裁剪再把 required RC 整体补回边界外”。
- `required RC must-cover` 当前只对 directional boundary 内的 `local required RC` 成立。
- `Step7` 只负责最终业务发布，不重新定义 `required / support / excluded / foreign`。
- `terminal_case_records/<case_id>.json` 是 internal full-input 的 authoritative terminal state；`t03_streamed_case_results.jsonl` 是 compact append log。

## 6. 文档索引

- 正式契约：`INTERFACE_CONTRACT.md`
- 业务步骤与实现阶段映射：`architecture/11-business-steps-vs-implementation-stages.md`
- 方案策略：`architecture/04-solution-strategy.md`
- 质量要求：`architecture/10-quality-requirements.md`
- 历史 closeout：
  - `architecture/04-step3-closeout.md`
  - `architecture/06-step45-closeout.md`
  - `architecture/08-step67-closeout.md`
- T02 继承边界：`architecture/09-t02-inheritance-boundary.md`

历史 closeout 文档用于追溯阶段性实现，不替代当前 `Step1~Step7` 正式业务结构。
