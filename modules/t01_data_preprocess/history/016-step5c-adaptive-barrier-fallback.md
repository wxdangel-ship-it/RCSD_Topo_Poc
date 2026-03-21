# 016 - Step5C Adaptive Barrier Fallback

## 背景
- 样例：`XXXS5`
- 问题：长 corridor 期望最终兜底形成 `997356__39546395`，但旧实现只构出：
  - `S2:997356__1029576`
  - `S2:1026960__39546395`
  - `STEP5C:1029571__39546395`
- 已确认旧阻塞不只是局部 road `direction`，更关键的是：
  - `Step5C` 把 `Step5B` 滚下来的历史 endpoint 机械继承为 `force_seed / force_terminate / hard-stop`
  - 当前 residual graph 中已退化为 through 的历史 endpoint 没有被重新判定
  - staged residual graph 无法对前序切段做 final fallback

## 为什么旧的“历史 endpoint = hard-stop”在 Step5C 不再成立
- `Step5A / Step5B` 仍是 strict staged residual 轮，保持刚性 boundary 语义有利于稳定收敛。
- `Step5C` 是 final fallback；此时前序轮次已剔除已构成 `segment_body` 的 roads，当前 residual graph 的拓扑语义可能已改变。
- 某些历史 endpoint 在 `Step5C residual graph` 上已经退化为：
  - `semantic incident degree = 2`
  - 且 `distinct neighbor semantic groups = 2`
- 这类节点继续被当作 `terminate + hard-stop`，会把真正应该在 final fallback 中连通的 corridor 人为截断。

## 新三集合语义

### 1. rolling endpoint pool
- 作用：
  - 记忆历史 endpoint
  - 并入当前 `Step5C residual graph` 上合法输入的宽集合
  - 继续作为 seed 候选来源
- 当前正式口径：
  - 历史 endpoint mainnode
  - 并上当前 residual graph 中满足：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64,2048}`
    - `grade_2 in {1,2,3}`
    的语义节点
- 约束：
  - `kind_2 = 1` 不能仅因字段条件进入 pool
  - 若某 `kind_2 = 1` 节点仍在 pool，只能因历史 endpoint 身份保留

### 2. protected hard-stop set
- 作用：
  - 定义 `Step5C` 中真正必须停止穿越的高置信 barrier
- 当前正式口径：
  - 只保护环岛 mainnode：
    - `kind_2 = 64`
    - `closed_con in {2,3}`

### 3. demotable endpoint set
- 作用：
  - 标识那些“历史上是 endpoint，但在当前 `Step5C residual graph` 上可降级为 through”的节点
- 当前最小正式判据：
  - 来自 `rolling endpoint pool - protected hard-stop set`
  - 按 semantic-node-group 计算：
    - `semantic incident degree = 2`
    - `distinct neighbor semantic groups = 2`

### 4. actual terminate barriers
- 作用：
  - 形成 `Step5C` 真正使用的 terminate barrier 集合
- 当前正式口径：
  - `protected hard-stop set`
  - 加上当前 residual graph 上未被 demote、仍保持真实 barrier 语义的 endpoint

## 为什么 protected set 当前只保留环岛
- 环岛 mainnode 在当前数据中的错误率相对更低，且已被模块正式定义为受保护语义路口。
- 将所有历史高等级边界继续全量塞回 `Step5C protected hard-stop set`，会直接把 final fallback 再次退化成旧的机械 terminate 继承。
- 因此本轮先只保留高置信对象：
  - 环岛 mainnode
- 其他历史 endpoint 统一交给当前 residual graph 的结构判定决定是否 demote。

## 本轮实现摘要
- `Step5C` 入口改为 adaptive barrier 模式：
  - `force_seed_node_ids = rolling endpoint pool`
  - `force_terminate_node_ids = actual terminate barriers`
  - `hard_stop_node_ids = protected hard-stop set`
- 搜索与收敛统一改读这套新 barrier 语义。
- 为避免“rolling pool 全进 force_seed 后又被 through 规则排除”，`Step1` 内核补了 `Step5C` 专用 through 例外：
  - 已 demote 的 rolling endpoint 既保留 seed 身份
  - 也允许作为 through 继续穿过

## 审计输出
- `STEP5C` debug 目录新增：
  - `step5c_rolling_endpoint_pool.csv/.geojson`
  - `step5c_protected_hard_stops.csv/.geojson`
  - `step5c_demotable_endpoints.csv/.geojson`
  - `step5c_actual_barriers.csv/.geojson`
  - `step5c_endpoint_demote_audit.json`
  - `target_pair_audit_997356__39546395.json`

## XXXS5 预期修复目标与本轮结果
- 目标：
  - 至少把 `997356__39546395` 的阻塞原因从 terminate rigidity 推进到真实剩余阻塞
  - 理想情况下在 `Step5C` 成功形成 candidate / validated / segment
- 本轮实际结果：
  - `STEP5C:997356__39546395` 已成功进入 `candidate`
  - 已成功进入 `validated`
  - `target_pair_audit_997356__39546395.json` 显示：
    - `blocked_by_actual_barrier = false`
    - `terminate_rigidity_cleared = true`
    - `remaining_blocker_type = none`
- 说明：
  - `Step5C` 已从机械 terminate 继承推进为 adaptive barrier fallback
  - 本轮不需要再用“历史 endpoint 刚性”解释 `XXXS5` 的长 corridor 失败
