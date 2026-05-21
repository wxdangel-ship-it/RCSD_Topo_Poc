# 01 Introduction And Goals

## 目标

T06 当前目标是在 T01 SWSD Segment 与 T05 Phase 2 SWSD-RCSD 语义路口关系已经产出的前提下，完成 Segment 融合前置判断：

1. 识别具备 EVD 与 anchor/fallback 基础的 SWSD Segment。
2. 在 copy-on-write RCSD 网络中抽取对应 Segment candidate。
3. 使用趋势类硬筛判断 candidate 是否可进入后续替换阶段。

## 成功判据

- Step1 能输出 EVD candidates、fusion units、rejected 与 summary。
- Step2 能输出 RCSD candidates、replaceable、rejected 与 summary。
- `fail4_fallback` 作为可融合 anchor 被正确接受。
- SWSD 单向方向不依赖 `pair_nodes` 顺序，而是由 road body 推导。
- `junc_nodes` 被作为内部通过 + 侧向阻断处理。
- 所有失败都有稳定 reason 与审计字段。

## 当前非目标

- 不执行 Segment 替换。
- 不重塑路口。
- 不修改 T01 / T05 输出。
- 不新增 repo 官方入口。
