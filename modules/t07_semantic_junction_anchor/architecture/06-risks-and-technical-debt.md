# 06 风险与技术债

## 1. 业务风险

- T07 是当前提升替换率的兜底措施，未来 RCSD 滚动构图方案下需要重新评估生命周期。
- 如果 Step3 消费失败 relation 或缺失 base 的 relation，会把不可消费关系提前交给 T05/T06。
- 如果 `kind_2=2048` 绕过 strict single-surface / single-SWSD / single-RCSD 条件直接建立 surface relation，会与 T03/T04 虚拟 T 型路口职责冲突。

## 2. 数据风险

- `mainnodeid` 组装依赖代表 node 存在；上游 nodes 结构异常必须显式审计。
- RCSDIntersection 面存在但无 RCSDNode 可消费时，应交回 T03/T04 虚拟锚定链路，不可强行发布 T07 relation。
- T05 `intersection_match_all` 字段契约变化会影响 Step3 补锚。

## 3. 结构债

`runner.py` 承载 Step1/2 多项职责，后续扩展时应拆分输入读取、语义路口组装、Step1 evidence、Step2 anchor 和 handoff 输出，同时保持 callable 签名稳定。

## 4. 治理缺口

T07 的文档和代码需要持续强调“不处理 Segment、不生成虚拟面”。新增关系补锚能力时，应先确认它属于 existing surface relation，而不是把 T03/T04 的虚拟锚定职责前移到 T07。
