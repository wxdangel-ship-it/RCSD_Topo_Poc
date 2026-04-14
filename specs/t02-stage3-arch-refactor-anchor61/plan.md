# T02 / Stage3 Anchor61 架构优化计划

## 1. 审计问题到重构动作映射

| 审计问题 | 重构动作 |
| --- | --- |
| Step3 更像 snapshot builder | 引入 Step3 canonical executor/result，后续步骤只消费其冻结结果 |
| Step5 与 Step6 存在双事实源 | 统一 foreign baseline / blocking / final residue 的结构边界 |
| Step6 late cleanup 承担业务补救 | 将 late cleanup 收编为 bounded optimizer，只更新 Step6 final state |
| Step7 仍依赖 legacy fallback | 将 Step7 改为纯消费 Step1~6 结果的终裁层 |
| `virtual_intersection_poc.py` 独占真实执行权 | 迁出 canonical live truth，主文件收回 orchestrator |
| tri-state / visual / summary 口径冲突 | 输出链与审计链单轨化，只消费 canonical result |
| full-input 被误表述为正式基线 | 契约同步 + 测试分层，降级为 regression-only |

## 2. 目标拓扑

- `stage3_step3_executor.py`：Step3 canonical legal-space layer
- `stage3_step5_foreign_model.py`：Step5 canonical foreign layer
- `stage3_step6_geometry_controller.py`：Step6 geometry controller
- `stage3_step7_verdict.py`：Step7 pure verdict
- `stage3_output_contract_adapter.py`：输出链单轨适配
- `virtual_intersection_poc.py`：orchestrator

## 3. 文件拆分策略

- 保留现有模块名时，优先在原文件内实现 canonical executor
- 必要时新增内部非入口模块
- 不新增公开 CLI 入口
- 所有输出逻辑必须从 monolith 删除主导权，而不是复制一层 wrapper

## 4. 输出链单轨化方案

- `review_index.json` 统一消费 canonical `Step7Result + AuditRecord`
- `review_summary.md` 与 `summary.json` 统一引用 tri-state 主口径
- `success` 布尔若保留，标记为兼容字段
- `kind_source` 纳入 row 级输出

## 5. tri-state / V1~V5 收口方案

- `accepted -> V1`
- `review_required -> V2`
- `rejected -> V3 / V4 / V5`
- 业务结果分类：
  - `accepted = 成功`
  - `review_required = 有风险`
  - `rejected = 失败`

## 6. 61 Anchor baseline 验证方案

- 以 `anchor61_manifest.json` 驱动正式验收层
- 每轮执行：
  - Anchor61 全量 case-package
  - Stage3 regression tests
  - full-input regression-only tests
- 输出自然执行分组统计与目视分组统计

## 7. 测试对齐方案

- 保留现有 `test_virtual_intersection_poc.py` 作为 regression + helper/unit/contract 层
- 保留 `test_virtual_intersection_full_input_poc.py` 作为 regression-only
- 新增 `test_anchor61_baseline.py` 作为正式验收层

## 8. 回归策略

- 每轮先跑 regression，再跑 Anchor61 正式验收
- 再做目视专项：
  - `698330`
  - `706389`
  - `584253`
  - `10970944`
  - `520394575`

## 9. 风险与停止条件

- 若发现任务书与主契约冲突，立即停止
- 若实现开始演化为 case 特判，立即回滚该方向
- 若 Step6/Step7 仍主要依赖 late pass 或 legacy fallback，本轮不得宣告完成
