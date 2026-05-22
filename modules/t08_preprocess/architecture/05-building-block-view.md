# 05 构建块视图

## 实现构件

- `vector_io.py`：共享 GPKG / Shapefile / GeoJSON 读写、CRS 处理与字段解析。
- `shp_to_gpkg.py`：Tool1 基础矢量格式转换 callable runner。
- `road_preprocess.py`：Tool2 callable runner。
- `nodes_type_aggregation.py`：Tool3 callable runner。
- `junction_type_repair.py`：Tool4 路口类型错误识别 callable runner。

## 入口构件

- `scripts/t08_tool1_vector_convert.py`
- `scripts/t08_tool2_road_preprocess.py`
- `scripts/t08_tool3_nodes_type_aggregation.py`
- `scripts/t08_tool4_junction_type_repair.py`

## 测试构件

- `tests/modules/t08_preprocess/test_tool1_vector_convert.py`
- `tests/modules/t08_preprocess/test_tool2_road_preprocess.py`
- `tests/modules/t08_preprocess/test_tool3_nodes_type_aggregation.py`
- `tests/modules/t08_preprocess/test_tool4_junction_type_repair.py`
