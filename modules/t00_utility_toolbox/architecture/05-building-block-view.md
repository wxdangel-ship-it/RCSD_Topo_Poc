# 05. Building Block View

主要构件：

- `specs/t00-utility-toolbox/*`
  - 固化 Tool1 至 Tool10 的需求基线
- `modules/t00_utility_toolbox/README.md`
  - 模块入口说明
- `modules/t00_utility_toolbox/INTERFACE_CONTRACT.md`
  - 输入、输出、覆盖、异常和摘要契约
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/common.py`
  - CRS、IO、日志、摘要等共享底层能力
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/patch_directory_bootstrap.py`
  - Tool1 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/drivezone_merge.py`
  - Tool2 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/intersection_merge.py`
  - Tool3 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/road_patch_join.py`
  - Tool4 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/road_kind_enrich.py`
  - Tool5 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/shapefile_geojson_export.py`
  - Tool6 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/geojson_to_gpkg_export.py`
  - Tool7 实现
- `src/rcsd_topo_poc/modules/t00_utility_toolbox/json_point_to_gpkg_export.py`
  - Tool10 实现
- `scripts/t00_tool1_patch_directory_bootstrap.py`
- `scripts/t00_tool2_drivezone_merge.py`
- `scripts/t00_tool3_intersection_merge.py`
- `scripts/t00_tool4_a200_patch_join.py`
- `scripts/t00_tool5_a200_kind_enrich.py`
- `scripts/t00_tool6_node_export.py`
- `scripts/t00_tool7_geojson_to_gpkg.py`
- `scripts/t00_tool9_divstripzone_merge.py`
- `scripts/t00_tool10_json_point_export.py`
