# 05 Building Block View

## 稳定阶段链

```text
strict input read -> semantic junction assembly -> representative node selection -> Step1 has_evd -> Step2 anchor recognition -> Step3 relation backfill -> output/audit/perf
```

## 构件职责

### 输入读取

- 读取 `nodes / DriveZone / RCSDIntersection`。
- Step3 另读 T05 `intersection_match_all.geojson` 与输入 `RCSDNode`。
- 严格解析 CRS。
- 统一转换到 `EPSG:3857`。

### 语义路口组装

- 按 `mainnodeid` 成组。
- 空 `mainnodeid` 退化为 singleton。
- 多节点组识别代表 node。

### Step1

- 判断代表 node `kind_2` 是否属于 `{4, 8, 16, 64, 128, 2048}`。
- 只对处理范围内语义路口执行 `DriveZone` 命中。
- 写代表 node `has_evd`。

### Step2

- 只处理 `has_evd = yes`。
- 判断组内 node 与 `RCSDIntersection` 的空间命中关系。
- 输出 `is_anchor / anchor_reason`。
- 输出 `node_error_1 / node_error_2` 审计。
- 输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`。

### Step3

- 只处理 `kind_2 in {4, 8, 16}`、`has_evd = yes`、`is_anchor = no` 的代表 node。
- 读取 T05 relation 主表中 `target_id / base_id / status`。
- 校验成功 relation 的 RCSD `base_id` 是否存在于输入 `RCSDNode.id/mainnodeid`。
- 输出 `intersection_match_t07.geojson` 并补写代表 node `is_anchor = yes / anchor_reason = NULL`。
- 输出复制 Step2 结果的 `t07_rcsdintersection_anchor_surface.gpkg`。
- 输出合并 Step2 evidence 与 Step3 成功补锚成果的 `t07_swsd_rcsd_relation_evidence.csv/json`，并记录 Step2 / Step3 锚定数量。

### 输出与审计

- 写完整 `nodes.gpkg`。
- Step2 写 `t07_rcsdintersection_anchor_surface.gpkg / t07_swsd_rcsd_relation_evidence.csv/json`。
- Step3 写 `intersection_match_t07.geojson / t07_rcsdintersection_anchor_surface.gpkg / t07_swsd_rcsd_relation_evidence.csv/json`。
- 写 summary / audit / perf。
- 不写 Segment 工件。
