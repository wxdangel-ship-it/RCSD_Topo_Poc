# 06 风险与技术债

## 1. 业务风险

- 如果 T08 输出未被明确纳入全量链路，T01/T03/T04/T05/T06/T09 可能消费字段语义不一致的原始数据。
- 如果 Tool6 质检结果未经人工确认直接修复，会把候选误判固化为输入事实。
- 如果 restriction / arrow 显性化被误读为最终规则，会与 T09 职责冲突。

## 2. 数据风险

- 原始 SWSD/RCSD 数据字段大小写、CRS、非空间表和几何类型差异较大，需要依赖每个工具的字段解析和 summary 审计。
- RCSDNode 的 `mainnodeid` 组语义若被 Tool9 单点过滤破坏，会直接影响 T05/T06。
- Road `kind` token 格式异常会影响 Tool2/4/5 的事件 Road、辅路豁免和 T-pair 虚拟连通判断。

## 3. 结构债

T08 工具数量多，脚本、callable、contract 和 README 容易不同步。后续新增 Tool 或改变 Tool 输出命名时，应先更新 `INTERFACE_CONTRACT.md` 和入口登记。

## 4. 治理缺口

T08 与 T10 的关系需要保持清晰：T08 是独立前置预处理、质检与修复模块，不由 T10 v1 Case runner 调用；内网全量总控可以把 T08 作为独立前置阶段串入。
