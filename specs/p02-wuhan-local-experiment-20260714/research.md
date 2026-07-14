# P02 武汉局部实验现状研究

## 1. 源事实结论

- 正式主链为 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- 本次因缺少道路面、导流带和 RCSDIntersection，明确缩减为 `T08 -> T01 -> T05 -> T06`。
- T05 已支持 `--t11-manual-relation`，正向类型为 `1v1_rcsd_junction / 1vN_rcsd_junction / 1v1_rcsd_road / 1vN_rcsd_road`。
- T05 Phase2 的当前 callable 仍要求 surface、fusion audit 和 T07/T02/T03/T04 路径；P02 运行时提供显式空兼容工件，不修改 T05 官方接口，也不声称相应模块运行成功。
- T06 只能把 T05 发布 relation 作为上游关系事实；P02 原始人工表不直接进入 T06。

## 2. 数据检查

| 数据 | 要素数 | 几何 | CRS |
|---|---:|---|---|
| `node.geojson` | 143 | Point | EPSG:4326 |
| `road.geojson` | 163 | LineString | EPSG:4326 |
| `RCSDNode.geojson` | 655 | Point | EPSG:4326 |
| `RCSDRoad.geojson` | 469 | LineString | EPSG:4326 |

- 坐标范围对应武汉局部区域；原始目录名 `XiAn_Test` 仅作为历史路径保留。
- `node.geojson` 只有 `closed_connect`，值域为 `0/2/3`；无 `closed_con`。
- 用户确认 `closed_connect` 与 `closed_con` 完全等价。
- SWSD 缺失端点 ID：`500284735 / 505284498 / 602284489 / 605284198`。
- RCSDRoad 有 9 个端点引用不在局部 RCSDNode 切片中。

## 3. 人工关系研究

- 13 条为 SWSD 语义路口到 RCSD 语义路口，按 T11 `1v1_rcsd_junction` 落盘。
- 3 条为 SWSD 语义路口到 RCSDRoad：`611463745` 按 T11 `1v1_rcsd_road` 落盘；`521458225 / 612028267` 分别关联两个 RCSDRoad，按 `1vN_rcsd_road` 落盘。
- 新增确认的 `5855295910117512 / 5855296278768745` 已在原始 RCSDRoad 中验证存在。
- Tool4/Tool5 可能改变 SWSD `mainnodeid`，因此 raw `target_id` 必须在 Tool5 后 canonicalize。
- T11 QGIS 规则对 RCSDNode 选择使用有效 `mainnodeid`，空/0 时回退 `id`；用户提供的 13 个 RCSDNode ID满足这一语义。
- `604021088` 和 `620020914` 共享 `5855296278770613`，属于允许的 many-target-to-one-base 审计，不构成 one-target-to-many-base 阻断。

## 4. 选定方案

1. 在 T08 Tool3 统一归一输入别名。
2. P02 保存 raw manual CSV。
3. Tool5 完成后，P02 callable 读取最终 Nodes，生成 converted manual CSV 与 transform audit。
4. T05 Phase2 从 Tool1 转换后的完整 RCSD 数据 copy-on-write，消费 converted manual CSV，不生成 local clip。
5. T06 执行 Step1-3，并以 replacement plan 与 topology audit 收口。

## 5. 未采用方案

- 不直接把 raw target 交给 T05：会丢失复杂路口聚合后的 canonical 身份。
- 不修改 T05 接口以移除空 surface/evidence 路径：本轮可用显式空兼容工件完成，避免扩大官方接口变更。
- 不在 T06 直接注入人工关系：违反 relation-first 和 T05/T06 责任边界。
- 不补造缺失端点 Node，也不删除引用缺失端点的 Road：前者会形成 silent topology fix，后者会改变用户要求的完整输入。

## 6. 实验中确认的兼容事实

- RCSD 原始字段使用 `Id/MainNodeId/SubNodeId/SNodeId/ENodeId` 大小写形式；T05 新增节点必须沿用模板字段名，T06 输入读取统一大小写无关归一并对异值冲突阻断。
- 复杂路口构建后出现 3 组同 canonical target、不同 RCSD junction selected ID，按用户“原始关系后续转换”要求升级为 `1vN_rcsd_junction`，不是冲突。
- 人工选中的 RCSDRoad `5855295910117438` 引用缺失端点；完整输入仍保留该 Road 并审计，不补造 RCSDNode。

## 7. 历史 local clip 复核与当前结论

- 原始 `5855295910117428` 为 `7601 -> 7708`，原始 `5855295910117379` 为 `7708 -> 7807`，两条 Road 在 `7708` 首尾相接且 `Direction=2` 连续。
- `5855295910117379` 的终点几何与人工锚定 RCSDNode `5855296278770582` 精确重合，距离为 `0m`；该节点 `CrossLid` 包含 `5855295910117379`。
- 旧 local clip 只按 `RCSDNode.Id` 检查端点，因 `7807` 缺失而删除整条 `5855295910117379`，导致 T05 输入提前断路。
- run03 曾在 P02 工作副本中以人工锚定节点、`CrossLid`、唯一精确几何重合执行端点归一。
- 当前用户要求撤销裁剪和自动端点归一：完整 469 条 RCSDRoad 进入 T05；`CrossLid` 不因单次样本被提升为 T05/T06 强规则。
- 2026-07-14 用户先逐项确认 `5855295910117569.ENodeId` 与 `5855295910117517.SNodeId` 两项修正，随后授权其余 7 项精确端点错配修正。9 项最终清单落盘在 `modules/p02_wuhan_local_experiment/endpoint_overrides/p02_confirmed_endpoint_overrides.csv`，只驱动 P02 copy-on-write 工作副本，不授权 `NodeLid/CrossLid`、同坐标或最近点运行时规则。

## 8. 并行 RCSD 通道归属结论

- `609020493_61493884` 与 `3086610_609284657` 在同一锚定路口区间存在两条可用 RCSD 通道。旧 Step2 先把两条通道都纳入大 Segment，再把小 Segment 的视觉一致通道判为 Road conflict，导致跟踪落到另一条 Segment 的通道。
- 正确修复点是 replacement plan 的通道归属，不是修改人工 relation：小 Segment 的中间锚点 `611463745 -> 5855296278770685`、`508350640 -> 5855296278770582` 只被 `5855295910117380 / 5855296278768752 / 5855296278768753 / 5855295910117379 / 5855296278768576` 有序覆盖，因此该 5 段通道归属小 Segment；`5855295910117399 / 5855295910117397 / 5855295910117569 / 5855296278768716` 归属大 Segment。
- 通道选择优先级必须为“正式锚定关系 > required junction 有序相对位置 > 几何距离”。相邻 plan 的 peer 通道不能补足当前 Segment 自身缺失的中间锚点，最终全图连通也不能替代这一局部归属约束。
