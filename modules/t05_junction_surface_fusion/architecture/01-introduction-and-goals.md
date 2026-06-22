# 01 引言与目标

## 1. 文档定位

本文件说明 T05 的架构背景、目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，Phase 1 / Phase 2 实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T05 是项目路口 1:1 关系层的统一发布模块。T07、T03、T04 分别解决已有路口面、常规虚拟路口和复杂虚拟路口的锚定证据；T05 将这些证据收口为统一路口面、SWSD-RCSD 语义路口关系主表和 copy-on-write RCSD 网络成果。

## 3. 目标

- Phase 1 将多来源 accepted surface 归一、分组、融合并发布为 `junction_anchor_surface.gpkg`。
- Phase 2 消费 relation evidence、final nodes 和 RCSDRoad/RCSDNode，发布 `intersection_match_all.geojson`。
- 对 road-only、multi-RCSDNode、复杂路口、环岛和 T07 relation-only target 执行可审计 junctionization。
- 保证一个 SWSD `target_id` 在最终关系主表中最多只有一条成功 relation。

## 4. 非目标

- Phase 1 不建立最终关系表，不打断 RCSDRoad，不新增 RCSDNode。
- Phase 2 不重新融合路口面，不原地修改输入 RCSDRoad/RCSDNode，不回改 T07/T03/T04 主链。
- T10 feedback 只能作为补充证据，不单独创建 SWSD-RCSD relation。

## 5. 架构边界

T05 的 Phase 1 代码由 `normalizer.py`、`fusion.py`、`outputs.py`、`runner.py` 等模块承载；Phase 2 由 `phase2_runner.py`、relation evidence、junctionization、cardinality 和 graph consumability 审计相关模块承载。内网脚本只负责组织输入与调用，不改变模块契约。
