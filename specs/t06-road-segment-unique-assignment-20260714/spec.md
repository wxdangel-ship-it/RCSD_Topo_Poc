# T06 RCSD Road—Segment 唯一分配规格

**Feature Branch**: `codex/p02-wuhan-local-experiment-20260714`
**Created**: 2026-07-14
**Status**: Ready for implementation
**Input**: 用户确认普通 RCSD Road 必须唯一分配至 Segment；复杂路口、环岛内部及独立连通 Road 可不归属 Segment，不能用多值 Segment 关系代替正式所有权。

## 1. 目标与边界

本轮统一 T06 的“替换执行组、Road carrier、Road owner”三层语义：

- `path_corridor_group` 只表达必须成组验证、成组成功或成组回退的原子替换事务，不授予组内 Road 多 Segment 所有权。
- 普通 RCSD Road 若进入 Segment replacement，必须按 `正式锚定关系 > required junction 有序相对位置 > 几何距离/视觉偏差` 收敛到一个 `owner_segment_id`。
- 复杂路口/环岛内部 Road 与独立 connectivity Road 可以进入 F-RCSD，但不归属任何 Segment。
- `t06_swsd_segment_ids` 只表达正式 owner：唯一 owner 时为单元素数组，无 owner 时为空数组。

不修改 T01 Segment 构建、T05 relation、人工锚定关系、输入 RCSD Road/Node、正式入口或 T09 消费规则。

## 2. 用户场景与独立验收

### US1 - 普通 Road 唯一分配（P1）

作为 T06 使用者，我需要同一条普通 RCSD Road 最终只属于一个 Segment，避免邻近、长短嵌套或并行 Segment 重复宣称同一 Road。

**独立验收**：P02 run08 当前 4 条普通重复 Road 分别收敛到 `3086610_609020493 / 61493884_84957918 / 84957918_501021044`，非 owner Segment 删除该 Road 后仍满足自身方向与 required topology。

### US2 - 特殊路口内部 Road 无 Segment owner（P1）

作为拓扑审计者，我需要复杂路口和环岛内部 Road 保留在 F-RCSD，同时不把“关联多个入/出 Segment”误写成多 Segment owner。

**独立验收**：canonical 两端同属一个正式特殊语义路口且由 `special_junction_group_internal` plan 发布的 Road，输出 `owner_type=special_junction_internal / owner_segment_id='' / t06_swsd_segment_ids=[]`，并保留 `special_junction_ids / related_segment_ids` 审计。

### US3 - 独立连通 Road 无 Segment owner（P1）

作为指标维护者，我需要调头、平行连接或二度桥接 Road 保留独立 connectivity group，不计入任何 Segment owner 或 Segment 替换指标。

**独立验收**：`multi_segment_connectivity` Road 保持 `include_connectivity` 和 group/related Segment 证据，但最终 `t06_swsd_segment_ids=[]`。

### US4 - QA 硬门禁（P1）

作为 QA，我需要每轮运行都能证明最终 Road 多 Segment 分配为 0，而不是依赖人工抽查。

**独立验收**：summary 输出最终 RCSD Road 单 owner、无 owner、多 owner 数量；`final_rcsd_road_multi_segment_assignment_count` 必须为 0，否则运行失败。

## 3. 五类职责视角

### 产品

- Segment owner 是唯一业务归属，不等于 Road 与路口、连通组或替换事务的关联关系。
- 当前 P02 样本 8 条多值 Road 的目标结果为 4 条唯一归属、4 条不归属、0 条多归属。

### 架构

- `path_corridor_group` 保留原子执行组能力，但 group union 不能直接发布为成员 Segment owner。
- `special_junction_internal` 与 `multi_segment_connectivity` 是无 Segment owner 的两种正式类型。
- relation 使用独立字段表达 owner、特殊路口关联与 connectivity 关联。

### 研发

- 所有权构建优先识别 Step2 正式发布的特殊路口内部 Road。
- 所有权决策完成后统一重写 F-RCSD Road provenance、added-road 审计与 Segment relation，清除非 owner 引用。
- surface 后 refresh 必须复用同一收口规则。

### 测试

- 覆盖普通冲突裁决、特殊路口内部无 owner、connectivity 无 owner、relation 非 owner 裁剪和 final Road 单值/空值发布。
- 覆盖 split/final Road 通过 `final_road_ids` 继承原始 owner。

### QA

- CRS：空间判定只在 `EPSG:3857` 下执行；relation ID 不参与跨 CRS 距离计算。
- 拓扑：裁剪非 owner Road 后重新验证 Segment 有向 pair/required junction 通路，不做 silent fix。
- 几何：距离只作为锚定与相对位置无法区分后的末级证据。
- 审计：owner、special junction、connectivity、被裁剪引用和最终字段均可追溯。
- 性能：记录所有权收口耗时与 Road 数量；实现保持按 Road/关系线性扫描。

## 4. 功能需求

- **FR-001**：每条最终 RCSD Road 的正式 Segment owner 数 MUST 为 `0` 或 `1`。
- **FR-002**：`owner_type=single_segment` MUST 具有唯一 `owner_segment_id`，且所有 `final_road_ids` 的 `t06_swsd_segment_ids` MUST 等于该单元素数组。
- **FR-003**：`owner_type=special_junction_internal` MUST 没有 `owner_segment_id`，MUST 记录 `special_junction_ids` 与 `related_segment_ids`，且不计 Segment 指标。
- **FR-004**：`owner_type=multi_segment_connectivity` MUST 没有 `owner_segment_id`，其相关 Segment 仅记录在 connectivity group/related 字段中。
- **FR-005**：无 Segment owner 的最终 Road MUST 发布 `t06_swsd_segment_ids=[]`。
- **FR-006**：Segment relation 的 `frcsd_road_ids` MUST 删除已解析为其它 Segment owner、特殊路口内部或独立 connectivity 的 RCSD final Road；source=2 SWSD carrier 与无 ownership 记录的兼容对象不受影响。
- **FR-007**：relation MUST 新增 `related_special_junction_internal_road_ids`，与 `owned_frcsd_road_ids / related_connectivity_road_ids` 分离。
- **FR-008**：`path_corridor_group` 可以作为原子替换 action，但不能使同一 Road 发布多个 Segment owner；唯一裁剪后任一成员不满足自身硬审计时必须阻断或回退，不能恢复多归属。
- **FR-009**：summary MUST 输出 `final_rcsd_road_single_segment_assignment_count / final_rcsd_road_unassigned_count / final_rcsd_road_multi_segment_assignment_count`。
- **FR-010**：`final_rcsd_road_multi_segment_assignment_count > 0` MUST 作为运行错误，不得发布成功结果。
- **FR-011**：本轮 MUST NOT 修改 T05 relation、人工锚定、RCSD 输入端点或几何。
- **FR-012**：本轮 MUST NOT 新增 CLI、脚本或其它正式入口。

## 5. 成功标准

- **SC-001**：P02 run09 的 206 条最终 F-RCSD Road 多 Segment 分配数为 0。
- **SC-002**：`5855295910117467 / 5855296278768591 / 5855296278768608 / 5855296278768661` 唯一归属预期 Segment。
- **SC-003**：`5855296278768493 / 5855296278768642 / 5855296278768702` 为 `special_junction_internal` 且无 Segment owner。
- **SC-004**：`5855296278768511` 为 `multi_segment_connectivity` 且无 Segment owner。
- **SC-005**：P02 已替换 Segment 的有向 pair/required junction 审计无新增正式 fail。
- **SC-006**：所有新增/修改源码和测试文件保持低于 100KB，聚焦测试、T06 回归与 P02 run09 验证通过。
