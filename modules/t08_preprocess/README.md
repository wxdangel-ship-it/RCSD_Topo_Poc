# T08 预处理

`t08_preprocess` 是项目正式预处理模块。当前提供六个工具：

- Tool1：基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON。
- Tool2：Road 数据预处理，补充 `patch_id` 与原始 `kind`，并输出 `0a + 17` 删除事件 Road。
- Tool3：Nodes 类型聚合，补充 `kind_2 / grade_2` 并聚合环岛 mainnode。
- Tool4：T 型路口错误修复，基于 Nodes `kind_2` 输出完整 Nodes 与 audit Nodes，不改写输入。
- Tool5：复杂路口预处理，构建复杂分歧 / 合流路口，并可基于 `RCSDIntersection` 识别和处理错误 1 对多路口，输出 audit Nodes。
- Tool6：Nodes 类型质检，输出人工质检 CSV 与 `node_error_tool6.gpkg`，不改写输入 Nodes/Roads。

T08 成果输出文件名统一在扩展名前以 `_toolX` 结尾，`X` 为工具编号。

## 运行入口

```bash
.venv/bin/python scripts/t08_tool1_vector_convert.py --help
.venv/bin/python scripts/t08_tool2_road_preprocess.py --help
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py --help
.venv/bin/python scripts/t08_tool4_junction_type_repair.py --help
.venv/bin/python scripts/t08_tool5_complex_junction_preprocess.py --help
.venv/bin/python scripts/t08_tool6_nodes_type_qc.py --help
```

## 内网示例

```bash
.venv/bin/python scripts/t08_tool1_vector_convert.py \
  --input-shp /mnt/d/TestData/POC_Data/input/A200_road.shp \
  --input-shp /mnt/d/TestData/POC_Data/input/A200_node.shp \
  --input-geojson /mnt/d/TestData/POC_Data/input/A200_area.geojson \
  --input-gpkg /mnt/d/TestData/POC_Data/input/A200_node.gpkg
```

```bash
.venv/bin/python scripts/t08_tool2_road_preprocess.py \
  --road-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_road.gpkg \
  --patch-road-gpkg /mnt/d/TestData/POC_Data/input/rc_patch_road.gpkg \
  --raw-kind-road-gpkg /mnt/d/TestData/POC_Data/input/raw_road_kind.gpkg \
  --road-patch-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_tool2.gpkg \
  --road-patch-unmatched-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_unmatched_tool2.gpkg \
  --road-patch-kind-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_kind_tool2.gpkg \
  --event-road-0a-17-output /mnt/d/TestData/POC_Data/t08_preprocess/road/event_road_0a_17_tool2.gpkg \
  --progress-interval 10000
```

```bash
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_node.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_road.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation_tool3.gpkg \
  --progress-interval 10000
```

```bash
.venv/bin/python scripts/t08_tool4_junction_type_repair.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation_tool3.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_road.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_nodes_tool4.gpkg \
  --audit-nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_audit_nodes_tool4.gpkg \
  --progress-interval 10000
```

```bash
.venv/bin/python scripts/t08_tool5_complex_junction_preprocess.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_nodes_tool4.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_road.gpkg \
  --intersection-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/RCSDIntersection.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_nodes_tool5.gpkg \
  --roads-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_roads_tool5.gpkg \
  --audit-nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_audit_nodes_tool5.gpkg \
  --progress-interval 10000
```

```bash
.venv/bin/python scripts/t08_tool6_nodes_type_qc.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_nodes_tool5.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_roads_tool5.gpkg \
  --csv-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/node_error_tool6.csv \
  --error-nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/node_error_tool6.gpkg \
  --progress-interval 10000
```

## 文档

- 稳定契约：[INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)
- 架构说明：[architecture/](architecture/)
- 变更任务书：[../../specs/t08-preprocess/](../../specs/t08-preprocess/)
