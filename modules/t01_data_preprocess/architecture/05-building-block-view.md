# 05 构件视图

## 状态
- 当前状态：`模块级构件说明`
- 来源依据：`src/rcsd_topo_poc/modules/t01_data_preprocess/`

## 稳定阶段链
`working bootstrap -> roundabout preprocessing -> Step1/Step2/Step3 -> Step4 -> Step5A/Step5B/Step5C -> final refresh`

## 构件与职责

### 1. 入口与参数装配
- [skill_v1.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1.py)
- 职责：official runner、阶段编排、进度与性能摘要输出

### 2. 输入解析与兼容层
- [io_utils.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/io_utils.py)
- [working_layers.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/working_layers.py)
- 职责：原始输入读取、working copy 初始化、环岛预处理

### 3. 主流水线
- [step1_pair_poc.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py)
- [step2_segment_poc.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py)
- [s2_baseline_refresh.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/s2_baseline_refresh.py)
- [step4_residual_graph.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py)
- [step5_staged_residual_graph.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py)
- [endpoint_pool.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/endpoint_pool.py)
- 职责：首轮构段、refresh、residual graph 轮次、全量 endpoint pool 滚动

### 4. 报告与诊断
- [freeze_compare.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/freeze_compare.py)
- [slice_builder.py](/E:/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/slice_builder.py)
- 职责：baseline 包生成、freeze compare、样例切片与审计辅助
