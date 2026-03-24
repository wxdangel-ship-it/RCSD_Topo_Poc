# 01 引言与目标

## 文档状态
- 状态：`模块级架构说明`
- 当前正式业务 baseline 主体见：
  - [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md)
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)

## 模块定位
- 模块路径：`modules/t01_data_preprocess`
- 角色：
  - 在非封闭式双向道路场景中，逐阶段构建双向 Segment
  - 为后续 Segment 聚合与更高层拓扑分析提供稳定输入

## 模块目标
1. 在普通道路网络上稳定提取双向 Segment。
2. 通过 staged residual graph 从高等级逐轮扩展到更低等级。
3. 在构段过程中滚动刷新 `grade_2 / kind_2` 当前语义。
4. 在 Step6 形成可审计的 Segment 聚合输出。

## 文档边界
- `architecture/*`
  - 承载模块级源事实与 accepted baseline
- `INTERFACE_CONTRACT.md`
  - 承载字段与阶段输入输出契约摘要
- `README.md`
  - 承载使用说明、入口与文档索引
- `specs/t01-data-preprocess/*`
  - 承载本轮治理/整改的 spec-kit 过程文档，不作为 steady-state baseline 正本
