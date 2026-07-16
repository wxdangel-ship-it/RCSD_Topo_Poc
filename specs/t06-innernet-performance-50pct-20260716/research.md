# Research: T06 全量内网性能恢复

## 1. 已确认事实

- 内网运行提交为 `f870a83`，已包含六例性能提交 `6a1eb4e/34e5204`，不是部署版本遗漏。
- 从 T06 开始并继续执行 T11/T09 的流水线总耗时 `12:55:56`，T06 Step3 内部精确耗时 `32207.946s`。依据 launcher 起止边界与阶段日志 mtime，旧 T06 Step1/2、Step3 外层和总计分别推算为 `5432.081s`、`37496.218s`、`42928.299s`。
- Step3 surface-aware 主阶段约占 `99.2%`，日志明确出现六轮完整 replaceable 解析：`19419 / 19667 / 19281 / 19112 / 19005 / 19003`。
- heartbeat 531 次采样中，`_build_junction_states` 163 次（30.7%），Shapely 169 次（31.8%），重复 BFS 26 次（4.9%），relation context 全表扫描 23 次（4.3%）。
- 全量规模为 added RCSD Node `119295`、junction `28918`；当前 `_build_junction_states` 单轮理论组合约 `3.45e9`，六轮约 `2.07e10`。
- peak RSS `9365992 KB`，约占当时 WSL 物理内存 92%；无 job swap/OOM，但安全余量很小。
- pipeline 进程状态为 passed，但业务审计仍有 `surface_topology_fail_count=291`、`final_frcsd_topology_fail_count=15`，两种状态不能混用。

## 2. 六例优化为何未覆盖全量问题

- `specs/t06-performance-recovery-20260714/final-report.md` 明确记录未执行内网全量。
- 六例优化主要消除了重复正式发布、重复读取和部分 coverage/topology 审计成本；全量数据下的 `added nodes × junctions` 复杂度没有进入局部热点前列。
- 当前主干还合入了与六例性能提交并行开发的 T06 visual gate/ownership 逻辑；这些逻辑未经过同规模全量冻结。

## 3. 候选优化方向

1. 为 junction state 构建 `canonical semantic id -> candidate states` 反向索引，再按 replacement Segment 交集过滤。
2. 为 retained raw node、relation rows、construction failed nodes 建一次性索引。
3. 对同一 graph revision 预计算 connected-component id，替代重复 `_reachable_any` BFS。
4. 对相同 geometry digest + distance + cap/join 参数复用标量判定或有界 buffer；默认不跨 Case 保存 Shapely geometry。
5. 将六轮完整 Step3 区分为业务决策轮与最终物化轮；复用真正不可变上下文，但保留候选、回退和 hard-gate 判定。

## 4. 否决方向

- 不通过减少候选、抽样、降低几何精度或跳过审计来提速。
- 不恢复跨运行无界 geometry cache；上一轮试验已证明会增加峰值内存。
- 不用并行叠加六 Case 或 Step3 replay 掩盖单进程复杂度；全量内存余量不足。

## 5. 未决验证

- Step1/2 当前缺少精确 stage wall/RSS 分解，需要增加不改变业务的阶段边界观测。
- 当前 compact 包没有 GPKG 内容，全量 geometry/CRS 等价必须在内网原始 run root 上执行。
- Shapely top frame 缺少 caller stack，需要通过本地 1885118 profile 和全量下一轮 heartbeat 分类确认具体调用者。
