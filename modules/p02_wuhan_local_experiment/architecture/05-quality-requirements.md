# 05 质量要求

- CRS：记录输入 4326、处理 3857 和 relation CRS84 转换。
- 拓扑：不得 silent fix；未经确认的缺失端点保持原样并显式审计，不删除 Road、不补造 Node。用户确认覆盖必须旧值精确匹配、只改一个登记字段，并证明 Road 数量、ID、几何不变。
- 输入完整性：Tool1 转换后的 Road/Node 要素数与 ID 集合必须在 T05 输入处保持一致。
- 几何：road-only relation 必须由 T05 投影/split 解释。
- 审计：raw→canonical→published→carrier lineage 完整。
- 性能：记录阶段 wall time、要素数和可取得的资源信息。
- 回归：T08/T01/T05/T06 既有正式测试不因 P02 回退。
- 替换边界：无正式锚定关系的 Segment 不进入 replacement plan，最终保留 SWSD。
- 内网 Case 硬门禁：当前输入必须重现 109 Segment、12 条 T05 relation、7 个成功替换、206 条 F-RCSD Road、243 个 F-RCSD Node、正式拓扑失败 0 和普通 RCSD Road 多归属 0；任一不一致退出失败。
- QGIS：正式执行必须生成可回读 `.qgz`、预览图、图层清单和机器 QA；工程 datasource 只使用包内相对路径。
