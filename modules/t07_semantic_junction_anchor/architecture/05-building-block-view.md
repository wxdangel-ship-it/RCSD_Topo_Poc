# 05 Building Block View

## 稳定阶段链

```text
strict input read -> semantic junction assembly -> representative node selection -> Step1 has_evd -> Step2 anchor recognition -> output/audit/perf
```

## 构件职责

### 输入读取

- 读取 `nodes / DriveZone / RCSDIntersection`。
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

### 输出与审计

- 写完整 `nodes.gpkg`。
- 写 summary / audit / perf。
- 不写 Segment 工件。
