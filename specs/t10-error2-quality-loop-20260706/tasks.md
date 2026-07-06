# T10-Error-2 20 Segment 未替换 RCSD 质量闭环任务

## Specify

- [x] 确认本轮使用隔离 worktree。
- [x] 确认输入附件与 T11 manual archive 路径。
- [x] 确认本轮必须按根因迭代，不以一次跑通作为完成。
- [x] 确认每轮根因修复必须经过 20 Segment、`1885118`、T10 6 case 三层回归。
- [x] 确认 GIS / topology QA 五项硬检查。

## Plan

- [x] 建立 20 Segment baseline。
- [x] 建立附件 145 行 root cause audit。
- [x] 制定 Root A：T11 manual relation 进入 T05/T06。
- [x] 制定 Root B：T10 side-group endpoint candidate 进入 T05 grouping。
- [x] 制定 Root C：T11 manual + T10 side-group 组合验证。
- [x] 对剩余 Step1 / Step2 blocker 形成可修复性判定。
- [x] 确认本轮正式代码修复不涉及入口、CLI、模块契约或项目级源事实变更。

## Implement / Evidence Phase 1

- [x] 新增临时 `manual_t05_t06_rerun_from_csv.py`。
- [x] 新增临时 `rcsd_attachment_root_cause_audit.py`。
- [x] 完成 20 Segment baseline。
- [x] 完成 T11 manual-only 20 Segment rerun。
- [x] 完成 side-group-only 20 Segment rerun。
- [x] 完成 manual-only / side-group-only 的 `1885118` 与 T10 6 case gate。
- [x] 扩展临时 helper 支持 T10 side-group / pair-anchor 参数透传。
- [x] 完成 manual + side-group 20 Segment 组合 rerun。
- [x] 生成 manual + side-group 附件 145 行 root cause audit。
- [x] 对比 baseline / manual-only / side-group-only / combined 四版收益。

## Implement Phase 2

- [x] 汇总剩余 `t06_step1_evidence_or_anchor_blocked` 的 target / reason / 是否有正向 T11 relation。
- [x] 汇总剩余 `t06_relation_or_topology_semantic_blocked` 的 relation / direction / buffer / topology reason。
- [x] 输出不可自动修复清单：需要人工补标、源事实裁定或上游数据修复。
- [x] 对现有源事实内可修复项完成前置体量检查并修改最小代码。
- [x] 确认本轮不涉及入口或契约变更，无需同步 registry / contract。
- [x] 修复 Root D：visual conflict release 对 `segment_road_connectivity` hard fail 未无条件回滚。
- [x] 修复 Root E：同 canonical RCSD semantic node 被误判为 replacement plan 分歧。

## Test

- [x] 临时 helper `py_compile` 通过。
- [x] 20 Segment combined rerun 20/20 passed。
- [x] `1885118` combined gate passed。
- [x] T10 6 case combined gate passed。
- [x] 正式代码修改对应单元测试通过。

## QA

- [x] CRS 与坐标变换检查：关键输入 / 输出 / audit GPKP 均为 `EPSG:3857`。
- [x] 拓扑一致性检查：三层回归无新增 hard fail，无 silent fix。
- [x] 几何语义检查：新增替换可追溯到 relation / candidate / replacement unit。
- [x] 审计可追溯性检查：run root、输入、参数、输出可定位。
- [ ] 性能可验证性检查：summary 可定位 `produced_at_utc`，但本轮 helper 未记录 duration，作为工具缺口保留。

## Closeout

- [x] 列出已修改文件及目的。
- [x] 列出已验证 run root 与核心指标。
- [x] 列出待确认的源事实、人工复核和未修复 blocker。
