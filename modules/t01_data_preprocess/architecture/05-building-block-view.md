# 05 构件视图

## 入口与编排
- [skill_v1.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1.py)
- 职责：
  - official runner
  - 阶段编排
  - 进度与性能摘要输出

## 输入与 working layers
- [io_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/io_utils.py)
- [working_layers.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/working_layers.py)
- 职责：
  - 输入读取与兼容层
  - working copy 初始化
  - 环岛预处理

## 主流程组件
- [step1_pair_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py)
- [step2_segment_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py)
- [s2_baseline_refresh.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/s2_baseline_refresh.py)
- [step4_residual_graph.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py)
- [step5_staged_residual_graph.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py)
- [endpoint_pool.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/endpoint_pool.py)
- 职责：
  - Step1-Step5 主流程
  - refresh
  - residual graph
  - endpoint pool / barrier 语义

## Step2 子域拆分
- [step2_release_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_release_utils.py)
- [step2_output_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_output_utils.py)
- [step2_trunk_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_trunk_utils.py)
- [step2_validation_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_validation_utils.py)
- [step2_graph_primitives.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_graph_primitives.py)
- [step2_runtime_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_runtime_utils.py)
- [step2_support_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_support_utils.py)
- [step2_candidate_channel_utils.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step2_candidate_channel_utils.py)
- 当前职责边界：
  - `step2_segment_poc.py` 聚焦 pair validation、segment_body tighten、same-stage arbitration 与 CLI/runner 编排
  - `step2_graph_primitives.py` 承担 undirected 连通性、component、bridge 检测等纯图算法 helper
  - `step2_runtime_utils.py` 承担 run id、out_root、progress callback 等运行时 helper
  - `step2_support_utils.py` 承担 shared support dataclass、semantic endpoint 与 output packaging helper
  - `step2_candidate_channel_utils.py` 承担 candidate channel、branch prune 与 segment-body candidate/refine helper
  - 其余四个文件分别承担 release、输出、trunk 子域、validation 包装

## 聚合与审计
- [step6_segment_aggregation.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/step6_segment_aggregation.py)
- [freeze_compare.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/freeze_compare.py)
- [slice_builder.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t01_data_preprocess/slice_builder.py)
- 职责：
  - Step6 Segment 聚合
  - compare / slice / 审计辅助
