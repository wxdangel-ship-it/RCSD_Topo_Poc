# T01 高层概览

## 1. 当前定位

- T01 是 `RCSD_Topo_Poc` 中的数据预处理模块
- 当前已经进入可编码的原型研发阶段
- 当前主线是：
  - Step1：`pair_candidates`
  - Step2：candidate validation + segment construction

## 2. 当前处理对象

- 上游输入：
  - `Road` 线图层
  - `Node` 点图层
- 当前核心处理语义：
  - 通过 `mainnodeid` 聚合语义路口
  - 在语义路口图上做 candidate 搜索与 validation

## 3. 当前产物定位

- Step1 产物用于表达“拓扑候选关系”
- Step2 产物用于表达“当前 POC 规则下通过验证的 segment”
- 所有产物都优先服务于：
  - QGIS 审查
  - 原型迭代
  - 规则澄清

## 4. 当前边界

- 当前不进入多轮 Segment 闭环
- 当前不进入 T 型路口轮间复核完整实现
- 当前不进入单向 Segment 阶段
- 当前不宣称生产规则已经封板
