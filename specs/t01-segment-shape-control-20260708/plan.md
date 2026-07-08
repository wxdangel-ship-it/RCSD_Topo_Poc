# T01 Segment 形态控制业务迭代 Plan

## 范围

本轮只修改 T01 Segment 发布前的工作层 road/node 处理与 T01 模块源事实文档；T06 仅用于验证与对比，不改 T06 代码。不新增常驻入口，不触碰项目级源事实文档。

## 产品视角

目标是提升 Segment 对真实道路形态的表达能力，而不是追求 Segment 数最少。长 Segment 只有在语义路口、几何转向或道路等级证据表明它跨越了两个业务方向时才拆分；近直行、同等级的连续主干保持现状。

## 架构视角

新增一个 T01 内部形态控制组件，放在 oneway completion 之后、Step6 aggregation 之前：

1. 按当前 `segmentid` 聚合 road，识别双向 Segment。
2. 在 Segment 内构建 semantic-node road 图。
3. 基于已契约字段识别可切分的内部语义路口。
4. 以切分节点为边界拆成 connected edge components。
5. 重写受影响 road 的 `segmentid`，保留审计字段。
6. Step6 继续按既有入口聚合，不改变对外调用方式。

## 研发视角

- 新增小模块承载形态控制算法，避免继续扩写接近 100KB 的既有大文件。
- 仅对 skill v1 的内部 pipeline 插入调用；不新增 CLI 参数。
- 对 `OnewaySegmentArtifacts` 增加形态控制 summary 字段，用于 final summary 透出。
- 若既有 side-attachment merge 与单向旁路保护冲突，优先缩小合并范围或记录审计，不扩大 T06 责任边界。

## 测试视角

- 单元测试覆盖：
  - 大于 60 度内部路口拆分；
  - 同等级近直行不拆分；
  - 两条 road 短双向段内部路口两侧道路等级不一致拆分；
  - 多 road 长链路仅道路等级不一致但近直行时不拆分；
  - 缺失拓扑/端点时审计跳过；
  - 新 `segmentid` 稳定且不冲突。
- 集成验证先跑 1885118，再跑 Segment20 与其余 5 case。

## QA 视角

对比口径固定为当前最新基线：

- 6 case baseline: `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_ce1cc72_20260707_153701/e2e_full`
- Segment20 baseline: `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_ce1cc72_20260707_153701/segment20_error2`

必须输出：

- T01 Segment count / sgrade 分布变化；
- T06 Step2 replaceable/rejected count；
- T06 Step3 relation status count；
- RCSD replacement count；
- 若指标回退，列出新增失败 Segment 与对应 T01 改动来源。

## 风险

- 过度拆分可能增加 T06 匹配碎片，需以 T06 指标守住不回退。
- 真实多路口识别过宽会误切近直行主干，因此必须同时要求多路口拓扑证据和角度/等级证据。
- 现有 1885118 中部分失败来自 T05/T06 关系，不应由 T01 形态控制强行修复。
