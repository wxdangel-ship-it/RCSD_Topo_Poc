# Plan

## 1. 审计结论到重构动作

| 审计/冻结结论 | 本轮动作 |
| --- | --- |
| 第二刀已证明 `584253` 可改善 | 将作用面扩展到同簇 `kind_2=4` 子簇并工程固化 |
| `10970944` 是弱保护样本 | 增加 focused regression，确保 compound_center 不漂移 |
| Anchor61 是唯一正式基线 | 每轮只以 Anchor61 验收，不混入 full-input 正式结论 |
| 不允许 case patch | 只做 Step6 侧 bounded regularization 与 cluster eval |

## 2. 代码范围

优先允许修改：

1. `src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step6_geometry_solve.py`
2. `src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step6_polygon_solver.py`
3. `src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step6_geometry_controller.py`

允许新增：

1. focused test 文件
2. 一个极小的 cluster evaluation helper

## 3. 工程动作

1. 明确 `kind_2=4` 作用子簇及保护边界。
2. 补 focused regression，覆盖：
   - `584253`
   - `705817`
   - `10970944`
   - `698330`
   - `706389`
   - `520394575`
3. 建立 `kind_2=4` cluster evaluation 输出。
4. 若 Step6 需要最小扩展，只允许在 bounded regularization 边界内完成。

## 4. 回归策略

必跑：

1. `test_stage3_step6_regularization.py`
2. `test_stage3_step6_geometry_controller.py`
3. 与 Step6 regularization / controller 相关 targeted tests
4. `test_anchor61_baseline.py`

## 5. Stop Conditions

出现以下任一项即停止实现：

1. 必须改 Step7 才能推进
2. 必须改 monolith 才能推进
3. 必须改 Step4 / Step5 才能推进
4. 保护样本回退
5. Anchor61 baseline 回退
6. 只能靠 case 特判才能推进
