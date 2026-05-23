# 03 上下文与范围

## 当前上下文

当前仓库已经从“纯骨架初始化”进入“治理底座 + 已登记模块并行维护”阶段。它与参考仓库 `Highway_Topo_Poc` 的关系是：

- 复用仓库级骨架、治理规则、文档契约体系、协作方式
- 不复用任何高速场景业务实现

## 当前范围

- 仓库级目录与文档骨架
- 项目级治理入口
- 仓库结构元数据
- 共享文本回传协议
- 模块启动模板
- 基础测试与 smoke
- `t00_utility_toolbox` 工具集合模块治理
- `t01_data_preprocess` 项目级登记与文档契约
- `t02_junction_anchor` 项目级登记与仓库级入口索引
- `t03_virtual_junction_anchor` 项目级登记、Step1~Step7 正式业务主链与 internal full-input 交付面
- `t04_divmerge_virtual_polygon` 项目级登记、Step1~Step7 正式文档面与 internal full-input 交付面
- `t05_junction_surface_fusion` 项目级登记、Phase 1 路口面融合发布、Phase 2 SWSD-RCSD relation 生产与 copy-on-write RCSD 网络输出
- `t06_segment_fusion_precheck` 项目级登记、Step1 SWSD 可融合 Segment 识别与 Step2 RCSD Segment candidate 抽取 / 趋势硬筛
- `t07_semantic_junction_anchor` 项目级登记、T02 Step1 / Step2 语义路口级 `has_evd / is_anchor / anchor_reason` 重构、模块内 callable runner 与内网脚本交付面
- `t08_preprocess` 项目级登记、Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合与 Tool4 路口类型错误识别入口、契约与测试
- `p01_arm_build` 项目级登记、P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 规则级还原文档契约、模块内 callable runner 与 review / final audit 交付面

## 当前范围外

- 未登记模块的无边界扩展
- 脱离模块契约的算法扩写
- 历史数据迁移
- 内网真实数据接入
- 专项回归、专项审计和专项工具链
