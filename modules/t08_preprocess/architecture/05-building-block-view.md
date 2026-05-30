# 05 构建块视图

## 实现构件

- `vector_io.py`：共享 GPKG / Shapefile / GeoJSON 读写、CRS 处理与字段解析。
- `shp_to_gpkg.py`：Tool1 基础矢量格式转换 callable runner。
- `road_preprocess.py`：Tool2 callable runner。
- `nodes_type_aggregation.py`：Tool3 callable runner。
- `junction_type_repair.py`：Tool4 路口类型修复 callable runner。
- `complex_junction_preprocess.py`：Tool5 复杂路口预处理 callable runner。
- `nodes_type_qc.py`：Tool6 Nodes 类型质检 callable runner。
- `traffic_restriction.py`：Tool7 交通限制显性化 callable runner。
- `lane_arrow.py`：Tool8 Laneinfo 箭头显性化 callable runner。

## 入口构件

- `scripts/t08_tool1_vector_convert.py`
- `scripts/t08_tool2_road_preprocess.py`
- `scripts/t08_tool3_nodes_type_aggregation.py`
- `scripts/t08_tool4_junction_type_repair.py`
- `scripts/t08_tool5_complex_junction_preprocess.py`
- `scripts/t08_tool6_nodes_type_qc.py`
- `scripts/t08_tool7_traffic_restriction.py`
- `scripts/t08_tool8_lane_arrow.py`

## 测试构件

- `tests/modules/t08_preprocess/test_tool1_vector_convert.py`
- `tests/modules/t08_preprocess/test_tool2_road_preprocess.py`
- `tests/modules/t08_preprocess/test_tool3_nodes_type_aggregation.py`
- `tests/modules/t08_preprocess/test_tool4_junction_type_repair.py`
- `tests/modules/t08_preprocess/test_tool5_complex_junction_preprocess.py`
- `tests/modules/t08_preprocess/test_tool6_nodes_type_qc.py`
- `tests/modules/t08_preprocess/test_tool7_traffic_restriction.py`
- `tests/modules/t08_preprocess/test_tool8_lane_arrow.py`
