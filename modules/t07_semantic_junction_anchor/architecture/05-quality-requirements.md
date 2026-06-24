# 05 质量要求

## 1. 业务正确性

- 代表 node 缺失是数据结构问题，不得 fallback 到其它 member node。
- 非处理 `kind_2` 写 `NULL`，不得写业务 `no`。
- Step3 不能用失败 relation 或不存在的 `base_id` 写锚定成功。
- `kind_2=128` 的补锚只能来自兼容 relation 成功关系；`kind_2=2048` 允许来自 Step2 strict surface 或兼容 relation 成功关系，两者都必须可追溯到唯一 RCSD 语义路口。

## 2. GIS 与拓扑要求

- 所有空间判定统一到 `EPSG:3857`。
- GeoJSON 缺 CRS 或 Shapefile 缺 `.prj` 时必须显式传 CRS override。
- `RCSDIntersection` 面内无可用 RCSDNode 时，不发布为可消费锚定。
- Step3 `intersection_match_t07.geojson` 输出 CRS84。

## 3. 回归要求

测试应覆盖 representative node 组装、1.5m evidence 容差、fail1 / fail2、RCSDNode gate、canonical ID、Step3 relation missing / failure / duplicate / base missing、cardinality QC 和 CRS84 输出。

## 4. 性能要求

T07 应记录阶段耗时、读取写出耗时和输出行数。性能优化不得改变 representative node 选择、Step1 evidence 命中、Step2 anchor 结果或 Step3 relation QC。
