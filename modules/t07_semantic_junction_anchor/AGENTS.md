# T07 模块执行约束

本目录只约束 `t07_semantic_junction_anchor`。

## 当前阶段

- 当前模块正式范围覆盖 T07 三个语义路口级步骤：
  - Step1：语义路口级 `DriveZone / has_evd gate`。
  - Step2：语义路口级 `RCSDIntersection / is_anchor / anchor_reason` 判定。
  - Step3：基于 T05 `intersection_match_all.geojson` 与输入 `RCSDNode` 对候选 SWSD 语义路口补写 `is_anchor = yes`。
- 当前已提供模块内 callable runner 与已登记内网执行脚本，业务契约、实现与测试应保持一致。
- 本模块继承 T02 Step1 / Step2 的代表 node 写值与空间命中基础口径，但 Step2 对 `kind_2 = 64 / 128 / 2048` 采用 T07 专属分流规则，并去除全部 Segment 处理。

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
- 不在上述集合内的语义路口，代表 node 的 `has_evd / is_anchor / anchor_reason` 均保持或写为 `NULL`。
- `has_evd / is_anchor / anchor_reason` 只写代表 node；从属 node 空值不是失败或未处理结果。
- Step3 仅处理代表 node `kind_2 in {4, 8, 16, 2048}`、`has_evd = yes` 且 `is_anchor = no` 的语义路口。
- Step3 只接受 T05 relation 主表中 `target_id = SWSD 语义路口 id`、`status = 0`、`base_id != 0` 的成功关系，并要求 `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在。
- Step3 接受后只写代表 node `is_anchor = yes`，`anchor_reason` 保持 `NULL`；同时输出 relation 子集 `intersection_match_tool7.geojson`。
- 当前无 repo 官方 CLI；正式执行面为模块内 callable runner，并由两个已登记内网脚本做包装。

## 必做验证

- 单元测试必须覆盖 Step1 allowed / disallowed `kind_2`、代表 node 写值、多节点组、singleton、Step2 `yes / no / fail1 / fail2 / NULL`、`kind_2 = 64 / 128` 专项规则写 `no` 且跳过冲突、`kind_2 = 2048` 同面命中写 `yes / t` 与不满足条件写 `no / NULL`、Step3 候选识别 / relation 成功 / RCSD 存在性校验 / `intersection_match_tool7.geojson` 输出、无 Segment 依赖。
- GIS / 拓扑任务必须显式覆盖 CRS、拓扑一致性、几何语义、审计追溯与性能可验证性。
- 提交前至少执行 T07 相关测试与 `git diff --check`。
