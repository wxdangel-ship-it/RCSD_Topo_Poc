# 04 Solution Strategy

## 主策略

1. Step1 / Step2 读取 `nodes / DriveZone / RCSDIntersection`，严格校验字段、CRS 与 geometry。
2. 将空间输入统一到 `EPSG:3857`。
3. 按 `mainnodeid` 组装语义路口；空 `mainnodeid` 退化为 singleton。
4. 识别代表 node；多节点组要求 `id == mainnodeid`。
5. Step1 按代表 node `kind_2` 过滤处理范围。
6. Step1 对处理范围内语义路口执行全组 node 的 `DriveZone` intersects/touches 判定，只有组内所有 node 均命中才写 `has_evd = yes`。
7. Step2 仅对 `has_evd = yes` 的语义路口执行 `RCSDIntersection` 判定。
8. Step2 先将 `kind_2 = 64 / 128` 写为基础 `no / NULL`，将 `kind_2 = 2048` 按“全组 node 命中同一个且唯一 `RCSDIntersection`”判定基础 `yes / t` 或 `no / NULL`。
9. Step2 对处理范围内类型形成 `RCSDIntersection -> SWSD 语义路口` 反向索引；同一面对应多个 SWSD 语义路口时，对代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 统一做 `fail2` 覆盖。
10. Step2 输出 `nodes`、语义路口级 summary、audit、perf、node error 工件，以及 T07 版 T02 handoff 成果 `t07_rcsdintersection_anchor_surface.gpkg / t07_swsd_rcsd_relation_evidence.csv/json`。
11. Step3 独立读取 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`。
12. Step3 处理代表 node `kind_2 in {4, 8, 16, 2048}` 的 SWSD 语义路口。
13. Step3 先读取 Step2 `t07_rcsdintersection_anchor_surface.gpkg`，对 SWSD-RCSDIntersection surface 1V1 结果，以 surface 覆盖输入 `RCSDNode` 的语义路口；仅有 1 个 RCSD 语义路口时建立 SWSD-RCSD 关系，多个时输出 `RCSDNode_error.gpkg`，0 个只写 audit / summary。
14. Step3 再选择 `has_evd = yes / is_anchor = no` 的 SWSD 语义路口作为 T05 relation 补充候选；只接受 `intersection_match_all.geojson` 中 `status = 0 / base_id != 0`、`base_id` 存在于输入 `RCSDNode.id/mainnodeid` 且未被前段占用的 relation。
15. Step3 对最终候选成功 relation 执行 T05 同口径基数质检，1:N、N:1 与重复 success target 写入 `relation_cardinality_errors.csv/json`；若出现 SWSD 1:N，则从 `intersection_match_t07.geojson` 移除该 SWSD 的所有关系并回写 `is_anchor = no`。
16. Step3 输出 `intersection_match_t07.geojson`，复制 Step2 `t07_rcsdintersection_anchor_surface.gpkg`，并合并生成带 Step2 / Step3 锚定数量的 `t07_swsd_rcsd_relation_evidence.csv/json`。

## 当前实现分层

- `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py`：承载严格输入读取、语义路口组装、Step1、Step2、Step2 handoff surface/evidence、summary / audit / perf 与组合 runner。
- `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_intersection_match.py`：承载独立 Step3 relation 补锚、`RCSDNode` 存在性校验、`intersection_match_t07.geojson`、合并 evidence 与 Step3 audit / summary / perf。
- `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/__init__.py`：导出稳定 callable runner。
- `scripts/t07_run_semantic_junction_anchor_innernet.sh`：内网执行包装；只负责路径、环境变量、repo `.venv` 与 runner 调用，不承载业务规则。
- `scripts/t07_run_step3_intersection_match_innernet.sh`：Step3 独立内网执行包装；可自动发现最近一次 T07 Step2 `nodes.gpkg`，也可显式覆盖输入路径。

后续如 Step1 / Step2 继续扩展，应优先把 `runner.py` 拆分为小文件，并保持对外 callable runner 签名稳定。

## 失败策略

- 业务 `no` 只表达空间未命中。
- 执行失败包括字段缺失、CRS 缺失、不可投影、geometry 缺失。
- 代表 node 缺失是数据结构问题，必须审计，不得 fallback。
- 非处理 `kind_2` 是业务跳过，稳定写为 `NULL`。
- Step3 relation 缺失、relation 失败或 RCSD `base_id` 缺失均不得写为锚定成功，必须在 Step3 audit 中说明。
