# T03 RCSD related/local_required/foreign_mask 三层语义契约

## 背景

706389 等真实 case 暴露出旧 `required / support / excluded` 口径无法同时解释两类事实：

- RCSD 下与当前路口同一路径、经二度 connector 串接的 `RCSDRoad` 应作为完整 `related` 语义证据展示。
- Step6 的 must-cover 仍只能作用于 directional boundary 内的 `local_required` 片段，不能要求边界外 RCSDRoad 全长覆盖。
- 真正用于 hard subtract 的对象应单独称为 `foreign_mask`，不能把完整 related 链路继续混入 hard foreign。

## 产品视角

- `related` 表示当前 SWSD 路口在 RCSD 下的强语义关联证据层，包括 required，以及从 required core 经二度非语义 connector 一跳补证且落在 Step3 局部 scope 外的 RCSDRoad。support 是独立辅助证据层，不自动进入 related。
- 共享同一非空 `mainnodeid` 且空间紧凑的多点 RCSDNode 复合组应按一个 RCSD 语义路口理解；当该组已有至少两个 incident RCSDRoad 被确认 related 时，同组 active node 应纳入 `related` 证据层，但同组其他 incident RCSDRoad 不得自动纳入 `related_rcsdroad_ids`。
- `RCSDNode` 进入 required/support 语义关联必须具备 incident RCSDRoad 证据；仅靠空间邻近且无 road 拓扑连接的孤立点不得升格为 related。
- `local_required` 表示 Step6 在 directional boundary 内需要硬覆盖的 RCSD 子集。
- `foreign_mask` 表示真正不属于当前 case、需要从最终面中 hard subtract 的 RCSDRoad 掩膜来源。
- review PNG 的深红 RCSDRoad 应表达强语义 `related` / `required`，support road 保持 amber 辅助证据表达。

## 架构视角

- 保留现有 `association_required_* / association_support_* / association_excluded_*` 文件名作为兼容输出，不做入口或文件名迁移。
- 在 Step4/Step5/Step6 status/audit 中新增三层字段：
  - `related_rcsdnode_ids`
  - `related_rcsdroad_ids`
  - `related_local_rcsdroad_ids`
  - `related_group_rcsdroad_ids`
  - `related_outside_scope_rcsdroad_ids`
  - `local_required_rcsdnode_ids`
  - `local_required_rcsdroad_ids`
  - `foreign_mask_source_rcsdroad_ids`
- `related_outside_scope_rcsdroad_ids` 不进入 Step6 hard mask；Step6 仍从 `excluded_rcsdroad_geometry` 生成 `foreign_mask`。
- `related_group_rcsdroad_ids` 不进入 Step6 full-length must-cover；Step6 仍只消费 directional boundary 内的 `local_required`。

## 研发视角

- Step4 在 required/support 之后构造 `related`：
  - `related_local_rcsdroad_ids = required_rcsdroad_ids`
  - active RCSDRoad 若不在 Step3 allowed buffer 内，且通过 `degree = 2` connector 与 `required_rcsdroad_ids` 一跳连通，才可进入 `related_outside_scope_rcsdroad_ids`
  - support-only road、related group road、远端 / 未打包 endpoint 不得作为 outside-scope related 外扩依据
  - 空间紧凑的多点 `mainnodeid` 复合语义组按 group 计算 degree；当 group 至少两个 incident road 已进入 related 时，同组 active node 进入 `related_rcsdnode_ids`
  - `related_group_rcsdroad_ids` 只记录已经由 local / outside-scope 路径规则命中的 group road 证据，不自动包含 group 的全部 incident road
  - 最终 `related_rcsdroad_ids = related_local_rcsdroad_ids ∪ related_outside_scope_rcsdroad_ids ∪ related_group_rcsdroad_ids`
- Step5 从 hard negative road 集合中分别排除 `required_rcsdroad_ids`、`support_rcsdroad_ids` 与 `related_rcsdroad_ids`，并显式输出 `foreign_mask_source_rcsdroad_ids`。
- Step6 不改变业务判定规则，只在 audit/status 中暴露三层字段。
- Review render 深红绘制强语义 `related_rcsdroad_geometry`，缺失时回退旧 required geometry；support road 保持 amber 辅助证据表达。

## 测试视角

- 合成用例覆盖：远端 outside-scope RCSDRoad 不得进入 `related_outside_scope`，应进入 `foreign_mask_source`；真正 unrelated active RCSDRoad 仍进入 hard mask。
- 合成用例覆盖：空间紧凑的多点 `mainnodeid` 复合语义组内，未命中 local / outside-scope 路径规则的 incident RCSDRoad 不得进入 `related_group`。
- 真实用例覆盖：706389 保持 `accepted / V1`，`5395781419598924` 进入 `related_local`，远端 `5395732498090175 / 5395732498090244` 不进入 `related_outside_scope`，而进入 `foreign_mask_source` 且不造成 Step6 foreign overlap。
- 真实用例覆盖：705817 的 `5387934112026680 / 5387934112026681 / 5387934112026682` 按同一复合 RCSD 语义路口处理，但 `5387934112027002 / 5387934112027016` 不进入 `related_rcsdroad_ids`。
- 渲染覆盖：association review 深红 draw call 使用强语义 `related_rcsdroad_geometry`，support 不被深红覆盖。

## QA 视角

- CRS：保持 `EPSG:3857`，不新增重投影。
- 拓扑：不通过 silent fix 改写上游几何语义；仅使用既有 `_clean_geometry` 输出规范。
- 几何语义：`related` 不等于全长 must-cover；`local_required` 不等于 full related；`foreign_mask` 不包含 related。
- 几何语义：related node 必须能追溯到 incident road 证据，避免纯点邻近误召回。
- 审计追溯：status/audit 需能解释 related/local_required/foreign_mask 的输入 id、connector 证据、`mainnodeid` group 证据和 mask source。
- 性能：新增逻辑仅在 active RCSDRoad 图内做 bounded 遍历，不改变并发和 Step3/Step6 业务规则。

## 非目标

- 不修改 Step3 legal-space / no-silent-fallback。
- 不修改 Step6/Step7 判定规则。
- 不新增、删除或重命名 CLI / shell wrapper。
- 不重命名正式输出文件。
- 不把 node 类 foreign/excluded 升级为 hard subtract。
