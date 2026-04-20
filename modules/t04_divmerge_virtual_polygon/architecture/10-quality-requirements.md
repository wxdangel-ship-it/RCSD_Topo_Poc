# 10 Quality Requirements

## 正确性

- CRS 与几何裁剪必须可追溯。
- Step1/2/3/4 的失败原因不得串层滥用。
- Step4 每个 event unit 的事实依据与位置必须可解释。

## 可审计性

- Step4 review 图必须能直接表达当前事件单元的主证据、主轴、参考点与正向 RCSD。
- CSV/JSON summary 必须能让人工快速定位复核对象。

## 可维护性

- 代码按领域能力分层。
- 避免单一超大 orchestrator。
- 与 T02/T03 的复用边界显式写入文档。

## 可回归性

- 至少保留 synthetic smoke。
- 至少跑 selected real-case batch。
