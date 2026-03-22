# 013 Step6 Formal Integration And Schema Migration

## 背景
- T01 此前的 official runner 实际止于 Step5C，Step6 仍被视为独立 POC。
- roads 正式输出长期混用 `s_grade / segmentid`，并保留了 `segment_id / Segment_id` 等 legacy alias 风险。
- 官方输入示例同时写 `Shapefile / GeoJSON`，不利于契约收敛、内外网脚本统一与 freeze compare 稳定性。

## 本轮决策

### 1. 官方输入统一到 GeoJSON
- official end-to-end
- official 分步入口
- Step6 standalone 入口
- 文档示例命令

以上全部统一按 `nodes.geojson / roads.geojson` 书写。  
Shapefile 仅保留为读取兼容层，不再作为官方推荐输入契约。

### 2. roads 正式输出统一到 `sgrade / segmentid`
- `sgrade` 取代 `s_grade`
- `segmentid` 继续保留
- `segment_id / Segment_id` 不再作为正式输出
- 读取阶段保留 alias 兼容，仅用于过渡期与 freeze compare 的 schema migration 兼容

### 3. Step6 正式纳入 official end-to-end
- official `t01-run-skill-v1` 现在完整跑到 Step6
- `debug=false` 仍会产出：
  - `segment.geojson`
  - `inner_nodes.geojson`
  - `segment_error.geojson`
- Step6 standalone 入口继续保留，用于单独调试与审计

## 重复处理优化
- Step6 不再在 official runner 中重新从磁盘读取 refreshed `nodes / roads`
- Step6 直接复用 Step5 的内存态结果：
  - `nodes`
  - `roads`
  - `node_properties_map`
  - `road_properties_map`
  - `mainnode_groups`
  - `group_to_allowed_road_ids`
- `debug=false` 下不再额外写 `nodes_step5_refreshed.geojson / roads_step5_refreshed.geojson` alias 文件
- freeze compare 对 refreshed `nodes / roads` 改为做语义归一化比较，避免把纯 schema 迁移误判为业务回退

## 过渡期兼容逻辑
- 读取 roads 时仍兼容：
  - `s_grade`
  - `segment_id`
  - `Segment_id`
- freeze compare 会把 baseline 的 `s_grade` 与 current 的 `sgrade` 归一化比较
- nodes compare 会忽略空占位的 `segmentid / sgrade` 字段
- 以上兼容仅用于过渡期，不代表官方输出契约仍接受旧字段作为新标准
