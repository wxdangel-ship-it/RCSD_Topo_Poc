# T01 高等级 Segment 业务迭代 Spec

## 背景

T01 在局部 XS3 用例中把高等级走廊切成多个局部 Segment，典型表现为 `1608731` 与 `1602185` 未形成业务期望的双向 Segment。审计显示，Step2 输出的 `endpoint_pool.csv` 包含所有 S2 seed / terminate，Step4 读取该文件作为 hard-stop 后，会把未成段的潜在端点也作为历史高等级边界，阻断后续高等级走廊追溯。

同时，单向补段后的 final fallback 仅覆盖 `direction in {2,3}` road，导致不满足 dead-end leaf 的 residual 双向 road 仍可能未构段。

## 用户故事

### US1 高等级走廊不被未成段端点过度截断

作为 T01 双向 Segment 构建使用者，我希望 Step4 / Step5 的历史 hard-stop 只保护上一轮已成立 Segment 的端点，未成段的潜在 seed / terminate 可以在当前轮继续追溯，从而形成更完整的高等级双向 Segment。

验收：
- XS3 中 `1608731` 与 `1602185` 应进入同一双向 Segment。
- Step4 / Step5 优先使用 `validated_pairs.csv` 作为历史边界来源。
- 旧产物缺失 `validated_pairs.csv` 时，仍可回退读取 `endpoint_pool.csv`。

### US2 最终兜底覆盖全部可发布 residual road

作为 T01 成果审计者，我希望在常规双向、单向、dead-end leaf 之后，所有仍未构段但端点可解析、非排除的 road 都能作为 single-road fallback 发布。

验收：
- `direction in {2,3}` residual road 继续以 `0-2单` single-road Segment 发布。
- `direction in {0,1}` residual road 以 `0-2双` single-road Segment 发布。
- `unsegmented_roads_summary.json` 中 XS2 / XS3 除裁剪缺失 node 或排除 formway 外应为 0。

## 功能需求

- FR-001: Step4 收集 S2 历史边界时 MUST 优先读取 `S2/validated_pairs.csv`，仅在该文件不存在时回退到 `S2/endpoint_pool.csv`。
- FR-002: Step5 收集 S2 / Step4 历史边界时 MUST 优先读取对应阶段 `validated_pairs.csv`，仅在旧产物缺失时回退到 `endpoint_pool.csv`。
- FR-003: 未出现在 validated pair 端点中的历史 `endpoint_pool.csv` 节点 MUST NOT 作为后续阶段 hard-stop。
- FR-004: final fallback MUST 覆盖 `direction in {0,1,2,3}` 且非排除、端点可解析、仍未构段的 road。
- FR-005: final fallback 对单向 road MUST 写 `sgrade=0-2单`，对双向 road MUST 写 `sgrade=0-2双`，并统一写 `segment_build_source=oneway_single_road_fallback`。
- FR-006: summary MUST 输出 final fallback 中单向与双向 built road 数量。
- FR-007: Step4 若在两个 `grade_2=1` 语义端点之间构成双向 Segment，MUST 写 `sgrade=0-0双` 与 `segment_build_source=step4_high_grade_terminal_demotion`。
- FR-008: Step6 对上述 Step4 标记 Segment 的中间 `grade_2=1, kind_2=4` 分歧 / 合流节点 MUST 审计豁免 `grade_kind_conflict`；普通 `0-0双` Segment 的同类冲突仍 MUST 输出错误。
- FR-009: final side-attachment merge MUST 在 final fallback 后、Step6 前执行，按候选 Segment 之间的 pair node 连通关系形成候选连通分量；候选之间仅通过非主 Segment 覆盖节点连通，共享同一个主 Segment 挂接点不得把多个孤立侧支合成一个分量；只有候选分量整体对同一个 `0-0双` 主 Segment 至少有两个挂接语义节点，且候选分量几何被主 Segment 的 `MAX_SIDE_ACCESS_DISTANCE_M` buffer 覆盖时，才允许整体并入主 Segment。
- FR-010: final side-attachment merge MUST 保留 `pre_merge_segmentid / pre_merge_sgrade / pre_merge_segment_build_source`，并输出 `side_attachment_merge_summary`、`side_attachment_merged_segment_count` 与 `side_attachment_merged_road_count`。
- FR-011: 双向主干上下行间距门限 MUST 使用 `max(50m, pair 两端语义路口内部成员节点最大距离)`，普通路段保持 50m，端点语义路口更宽时允许以该宽度作为有效门限。
- FR-012: final side-attachment merge 若候选连通分量可被多个 `0-0双` 主 Segment 包含，MUST 按挂接点数量多优先、距离短次优先、`segmentid` 稳定兜底进行仲裁，并输出仲裁审计；仅单点挂接主 Segment、不能经候选分量回挂形成首尾闭环的孤立候选 MUST 保留原 Segment。

## 非功能需求

- CRS：测试与审计必须确认输入 CRS，不进行 silent coordinate fix。
- 拓扑：缺失 endpoint node 的裁剪 road 不作为算法失败；其他 residual road 必须可追溯到原因或被构段。
- 几何语义：高等级走廊仍受上下行 road-body 间距门控约束，有效门限为 `max(50m, pair 两端语义路口内部成员节点最大距离)`。
- 审计：保留 baseline / after 的 Segment count、unsegmented count、关键 pair 命中情况。
- 性能：XS2 / XS3 本地用例必须完成全链路回归，避免 candidate 数异常膨胀。
