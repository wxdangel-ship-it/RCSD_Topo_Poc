# T02 任务清单

> 本文件是 T02 stage1 初始基线的变更任务工件。当前正式模块状态以 `modules/t02_junction_anchor/*` 与项目级治理文档为准。

## 1. 本轮文档任务 checklist

- [x] 建立 `specs/t02-junction-anchor/spec.md`
- [x] 建立 `specs/t02-junction-anchor/plan.md`
- [x] 建立 `specs/t02-junction-anchor/tasks.md`
- [x] 建立 `modules/t02_junction_anchor/AGENTS.md`
- [x] 建立 `modules/t02_junction_anchor/INTERFACE_CONTRACT.md`
- [x] 建立 `modules/t02_junction_anchor/README.md`
- [x] 建立 `modules/t02_junction_anchor/architecture/overview.md`
- [x] 建立 `modules/t02_junction_anchor/history/000-bootstrap.md`

## 2. 已确认业务规则 checklist

- [x] T02 总目标是双向 Segment 相关路口锚定
- [x] 当前采用两阶段推进：阶段一 gate，阶段二 anchoring
- [x] 当前只对阶段一形成稳定需求基线
- [x] 阶段一正式输入：`segment`、`nodes`、`DriveZone.geojson`
- [x] stage1 实际输入字段冻结为 `segment.id / pair_nodes / junc_nodes`
- [x] stage1 实际输入字段冻结为 `nodes.id / mainnodeid`
- [x] `mainnode` 仅作为业务概念名，`mainnodeid` 才是 stage1 实际输入字段
- [x] `working_mainnodeid` 不作为 stage1 正式输入字段
- [x] 阶段一路口来源只认 `pair_nodes` 与 `junc_nodes`
- [x] 单个 `segment` 内先对 `pair_nodes + junc_nodes` 去重
- [x] 去重后若无目标路口，则 `segment.has_evd = no` 且 `reason = no_target_junctions`
- [x] 路口组装规则：先查 `mainnodeid = J` 组，再查 `mainnodeid is NULL + id = J` 单点兜底
- [x] `s_grade` 逻辑字段兼容读取 `s_grade / sgrade`，两者不会同时出现
- [x] `s_grade` 正式分桶值写法冻结为 `0-0双 / 0-1双 / 0-2双`
- [x] `DriveZone` 判定只要组内任一 node 命中即成功，边界接触也算成功
- [x] 空间判定统一在 `EPSG:3857`
- [x] 代表 node 规则冻结：正常场景按 `id = junction_id`
- [x] 若代表 node 缺失，必须异常留痕，不能 silent skip
- [x] 环岛代表 node 当前继承 T01 既有逻辑，不由 T02 stage1 自行重定义
- [x] `nodes.has_evd` 只写代表 node，其余同组 node 保持 `null`
- [x] 找不到路口组时必须写 `reason = junction_nodes_not_found`
- [x] `segment.has_evd` 采用严格全满足规则
- [x] `summary` 按 `s_grade` 分桶，桶内按唯一路口 ID 统计
- [x] 阶段一非范围已明确写入文档

## 3. 待确认项 checklist

- [ ] Deferred：`pair_nodes` 历史示例尾缀 `_N` vs `_1` 的正式说明是否需要单独补充
- [ ] Deferred：阶段一审计留痕的稳定文件形态与最小字段集
- [ ] Deferred：环岛代表 node 的后续独立闭环规则
- [ ] Deferred：缺失 CRS 的上游数据质量兜底方式
- [ ] Deferred：阶段二锚定结果与概率 / 置信度输出定义

## 4. 后续编码前置条件 checklist

- [x] 完成 stage1 字段映射冻结
- [x] 明确 `s_grade` 兼容字段与正式值写法
- [x] 明确代表 node 规则与环岛继承约束
- [x] 明确空目标路口 `segment` 口径
- [x] 明确 `EPSG:3857` 空间判定口径
- [ ] 明确阶段一审计落盘契约
- [ ] 形成阶段一编码任务书
- [ ] 获得用户明确允许后再进入实现

## 5. 明确 blocked / deferred 的任务

- Blocked：无。本轮后已可进入 stage1 编码任务书准备。
- Deferred：阶段二 anchoring 主逻辑
- Deferred：成果概率 / 置信度实现
- Deferred：误伤捞回

## 6. 当前未启动的事项

- [ ] 阶段一代码实现
- [ ] 阶段二代码实现
- [ ] 概率 / 置信度实现
- [ ] 新运行入口
- [ ] 测试代码补充
