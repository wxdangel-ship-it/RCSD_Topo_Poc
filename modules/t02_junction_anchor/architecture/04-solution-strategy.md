# 04 方案策略

## 状态

- 当前状态：`模块级方案策略说明`
- 来源依据：
  - 官方 CLI 子命令
  - stage1 实现
  - 当前单元测试与 smoke

## 主策略

1. 通过统一 CLI 入口读取 `segment / nodes / DriveZone`
2. 对输入字段、CRS 与 geometry 做显式校验，不做隐式猜测
3. 从 `pair_nodes + junc_nodes` 提取单 `segment` 的目标 junction 集合并去重
4. 按 `mainnodeid` 分组 / 单点兜底组装 junction group
5. 在 `EPSG:3857` 下对 junction group 与 `DriveZone` 做空间 gate
6. 产出 `nodes.has_evd`、`segment.has_evd`、`summary`、`audit / log`

## 降级与失败策略

- 业务级 `no`：
  - `junction_nodes_not_found`
  - `representative_node_missing`
  - `no_target_junctions`
- 执行级失败：
  - `missing_required_field`
  - `invalid_crs_or_unprojectable`
- 设计原则：
  - 不能 silent skip
  - 不能把执行失败伪装成业务 `no`
  - 不能为环岛与代表 node 缺失补充新的泛化 fallback

## 文档策略

- 稳定阶段链与边界由 `architecture/*` 承担。
- 输入、输出、入口、参数类别与验收由 `INTERFACE_CONTRACT.md` 承担。
- `README.md` 只给操作者入口与常见运行方式。
