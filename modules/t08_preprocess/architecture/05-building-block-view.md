# 05 构建块视图

## 实现构件

- `vector_io.py`：共享 GPKG / Shapefile 读写、CRS 处理与字段解析。
- `shp_to_gpkg.py`：Tool1 callable runner。
- `road_preprocess.py`：Tool2 callable runner。
- `nodes_type_aggregation.py`：Tool3 callable runner。

## 入口构件

- `scripts/t08_tool1_shp_to_gpkg.py`
- `scripts/t08_tool2_road_preprocess.py`
- `scripts/t08_tool3_nodes_type_aggregation.py`

## 测试构件

- `tests/modules/t08_preprocess/test_tool1_shp_to_gpkg.py`
- `tests/modules/t08_preprocess/test_tool2_road_preprocess.py`
- `tests/modules/t08_preprocess/test_tool3_nodes_type_aggregation.py`
