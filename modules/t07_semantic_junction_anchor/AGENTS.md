# T07 模块执行约束

本目录只约束 `t07_semantic_junction_anchor`。

## 当前阶段

- 当前模块正式范围覆盖 T07 三个语义路口级步骤：
  - Step1：语义路口级 `DriveZone ∪ RCSDIntersection / has_evd gate`。
  - Step2：语义路口级 `RCSDIntersection / is_anchor / anchor_reason` 判定。
  - Step3：基于 T05 `intersection_match_all.geojson` 与输入 `RCSDNode` 对候选 SWSD 语义路口补写 `is_anchor = yes`。
- 当前已提供模块内 callable runner 与已登记内网执行脚本，业务契约、实现与测试应保持一致。
- 本模块继承 T02 Step1 / Step2 的代表 node 写值与空间命中基础口径，但 Step2 对 `kind_2 = 64 / 128` 采用 T07 专属分流规则；`kind_2 = 2048` 不在 T07 建立 SWSD-RCSD 关系，交由 T03 虚拟锚定；模块去除全部 Segment 处理。

## 禁止事项

- 不读取、生成或统计 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 `segment.has_evd`、`summary_by_s_grade` 或 `anchor_summary_by_s_grade`。
- 不实现 T02 Stage3 虚拟路口锚定。
- 不实现 T02 Stage4 div/merge polygon。
- 不新增 repo CLI、`tools/`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 与 `scripts/t07_run_step3_intersection_match_innernet.sh` 外，不新增其它 repo 级脚本入口。
- 不根据局部数据反推 `kind_2`、`mainnodeid` 或 `RCSDIntersection` 字段语义。

## 实现边界

- `kind_2` 是当前唯一正式类型判断字段；不兼容 `Kind_2`。
- `kind_2` 判断以语义路口代表 node 为准。
- Step1 仅处理代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 的语义路口。
- Step1 对处理范围内语义路口，必须组内所有 node 均落入或接触 `DriveZone ∪ RCSDIntersection` 才写 `has_evd = yes`；任一组内 node 未命中该合并 evidence 面则写 `has_evd = no`。
- 不在上述集合内的语义路口，代表 node 的 `has_evd / is_anchor / anchor_reason` 均保持或写为 `NULL`。
- `has_evd / is_anchor / anchor_reason` 只写代表 node；从属 node 空值不是失败或未处理结果。
- Step3 处理代表 node `kind_2 in {4, 8, 16}` 的语义路口，先用 Step2 surface 1V1 推导关系，再对 `has_evd = yes / is_anchor = no` 的候选使用 T05 relation 主表补充关系。
- Step3 只接受 T05 relation 主表中 `target_id = SWSD 语义路口 id`、`status = 0`、`base_id != 0` 的成功关系，并要求 `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在且未被 Step2 surface 1V1 阶段占用。
- Step3 必须输出 `RCSDNode_error.gpkg` 记录 Step2 surface 面内多个 RCSD 语义路口错误；必须对最终候选成功 relation 做 T05 同口径基数质检，并输出 `relation_cardinality_errors.csv/json`，覆盖 1:N、N:1 与重复 success target；若出现 SWSD 1:N，必须取消该 SWSD 已建立关系并回写 `is_anchor = no`。
- Step3 接受后只写代表 node `is_anchor = yes`，`anchor_reason` 保持 `NULL`；同时输出 relation 子集 `intersection_match_t07.geojson`。
- Step2 必须输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`；Step3 必须输出复制 Step2 surface 结果的 `t07_rcsdintersection_anchor_surface.gpkg`，以及合并 Step2 evidence 与 `intersection_match_t07.geojson` 成功补锚成果的 `t07_swsd_rcsd_relation_evidence.csv/json`，并记录 Step2 / Step3 锚定数量。
- 当前无 repo 官方 CLI；正式执行面为模块内 callable runner，并由两个已登记内网脚本做包装。

## 必做验证

- 单元测试必须覆盖 Step1 allowed / disallowed `kind_2`、代表 node 写值、多节点组、singleton、Step2 `yes / no / fail1 / fail2 / NULL`、`kind_2 = 64 / 128` 专项基础规则写 `no`、`kind_2 = 2048` 统一写 `no / NULL` 且不参与 T07 关系映射、`kind_2 in {4, 8, 16, 64, 128}` 一面多 SWSD 语义路口时统一 `fail2` 覆盖、Step2 handoff surface/evidence 输出、Step3 候选识别 / relation 成功 / RCSD 存在性校验 / `intersection_match_t07.geojson` 与合并 evidence 输出、Step3 relation 1:N / N:1 基数质检、无 Segment 依赖。
- GIS / 拓扑任务必须显式覆盖 CRS、拓扑一致性、几何语义、审计追溯与性能可验证性。
- 提交前至少执行 T07 相关测试与 `git diff --check`。
