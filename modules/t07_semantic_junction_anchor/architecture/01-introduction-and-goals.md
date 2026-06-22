# 01 引言与目标

## 1. 文档定位

本文件说明 T07 的架构背景、目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，Step1/2/3 实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T07 是项目路口 1:1 关系层中的已有路口面锚定模块。它迁移 T02 Step1/2 的语义路口级锚定能力，并增加独立 Step3 relation backfill，让已有 RCSDIntersection 或 T05 已发布成功 relation 的 SWSD 语义路口先进入 T05 handoff，避免 T03/T04 对已可锚定路口重复生成虚拟面。

## 3. 目标

- Step1 基于 `DriveZone ∪ RCSDIntersection` 判定代表 node 的 `has_evd`。
- Step2 基于 `RCSDIntersection` 和可选 `RCSDNode` 判定 `is_anchor / anchor_reason`。
- Step2 输出 T07 版 surface handoff 与 relation evidence。
- Step3 基于 T05 `intersection_match_all.geojson` 对符合条件的 existing surface 路口补写 relation anchor。
- 对 Step3 relation 做 T05 同口径 cardinality QC。

## 4. 非目标

- 不读取或输出 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不生成虚拟路口面。
- 不执行 div/merge polygon。
- 不新增 repo 官方 CLI。

## 5. 架构边界

`runner.py` 承载 Step1/2 与组合 runner；`step3_intersection_match.py` 承载独立 Step3 relation backfill。两个内网脚本只负责路径、环境和 runner 调用，不承载业务规则。
