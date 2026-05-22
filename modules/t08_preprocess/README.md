# T08 预处理

`t08_preprocess` 是项目正式预处理模块。当前提供三个工具：

- Tool1：基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON。
- Tool2：Road 数据预处理，补充 `patch_id` 与原始 `kind`。
- Tool3：Nodes 类型聚合，补充 `kind_2 / grade_2` 并聚合环岛、复杂分歧 / 合流 mainnode。

## 运行入口

```bash
.venv/bin/python scripts/t08_tool1_vector_convert.py --help
.venv/bin/python scripts/t08_tool2_road_preprocess.py --help
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py --help
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
  --road-patch-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch.gpkg \
  --road-patch-unmatched-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_unmatched.gpkg \
  --road-patch-kind-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_kind.gpkg \
  --progress-interval 10000
```

```bash
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_node.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/gpkg/A200_road.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation.gpkg \
  --progress-interval 10000
```

## 文档

- 稳定契约：[INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)
- 架构说明：[architecture/](architecture/)
- 变更任务书：[../../specs/t08-preprocess/](../../specs/t08-preprocess/)
