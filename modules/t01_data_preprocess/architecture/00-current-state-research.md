# 00 当前状态研究

## 当前状态
- 模块 ID：`t01_data_preprocess`
- 当前阶段：`active accepted baseline`
- 说明：
  - 从模块内部看，当前已形成 official end-to-end + Step6 的 accepted baseline。
  - 从仓库级模块生命周期看，当前已登记为正式 `Active` 模块。
- 研究目标：
  - 固化当前实现已经收敛的业务语义
  - 让模块级 architecture 文档与实现、契约、活动基线一致

## 当前输入证据
- 实现入口：
  - [skill_v1.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1.py)
  - [step2_segment_poc.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py)
  - [step4_residual_graph.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py)
  - [step5_staged_residual_graph.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py)
- 测试：
  - [tests/modules/t01_data_preprocess](/E:/Work/RCSD_Topo_Poc/tests/modules/t01_data_preprocess)
- 任务书与修正轨迹：
  - [history](/E:/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/history)
- 活动基线：
  - [t01_skill_active_eight_sample_suite](/E:/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/baselines/t01_skill_active_eight_sample_suite)

## 当前观察
- 当前业务目标已明确聚焦于普通道路上的双向路段逐级提取。
- working bootstrap、环岛预处理、统一 50m gate、全量 endpoint pool 滚动都已经进入实现。
- 文档层面此前存在“内容已收敛，但 architecture 目录未按模板结构承载”的缺口，本次已补齐。

## 后续观察点
- 后续是否将 Step6 之外的单向 Segment、封闭式道路扩展纳入新的正式构建轮次
- Step2 结构债是否需要在不改业务结果前提下继续细拆
