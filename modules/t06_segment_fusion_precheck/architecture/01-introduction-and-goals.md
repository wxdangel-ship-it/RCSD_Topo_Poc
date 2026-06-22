# 01 引言与目标

## 1. 文档定位

本文件说明 T06 的架构背景、业务目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，Step1-Step3 实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T06 位于项目从“路口 1:1 relation 建模”进入“数据替换执行”的承接位置。T01 提供 SWSD Segment，T05 提供 SWSD-RCSD 语义路口关系和 copy-on-write RCSD 网络。T06 基于这些输入构建 RCSDSegment、判断 replaceable、发布 replacement plan，并在 Step3 输出 F-RCSD Road / Node。

T06 不是简单按 T05 relation 替换 Segment。真实 RCSD 数据存在裁剪窗口不足、方向不一致、路口内部短连接、提前右转、road-only split、surface 证据缺失和 SWSD/RCSD carrier 差异。T06 的业务价值是在不放松 Step2 硬审计、不回写上游 relation 的前提下，把可替换对象、已解决问题、待上游处理问题和最终 F-RCSD 拓扑质量清楚分流。

## 3. 目标

- Step1 识别具备基础融合资格的 SWSD Segment。
- Step2 构建 buffer-based RCSDSegment，执行硬审计、特殊路口组门控、受限高置信重试、replacement plan 和 problem registry 发布。
- Step3 优先消费 replacement plan，执行标准 Segment、特殊路口组内部实体和 path-corridor group replacement。
- 输出 F-RCSD Road / Node、SWSD-FRCSD Segment relation、topology connectivity audit 和可选 surface topology audit。

## 4. 非目标

- 不修改 T01 / T05 / Step2 输入成果。
- 不把诊断文件当作 Step3 替换白名单。
- 不用 Step3 重判 rejected Segment。
- 不通过几何猜测回写 T05 relation 或新增上游 relation。
- 不新增 repo 官方 CLI。

## 5. 架构边界

T06 的 Step1、Step2、Step3 均有模块内 callable。脚本只负责内网包装和运行组织。T06 允许在当前 Segment 内做受限高置信 effective relation 重试，但成功也只进入 T06 当前 replacement plan，不改变 T05 relation 主表。
