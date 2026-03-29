# 024 Active Inventory Sync And Step2 Helper Split

## 日期
- 2026-03-29

## 背景
- 用户确认 `t01_data_preprocess` 需要重新登记回 repo 级 `Active` module inventory。
- `step2_segment_poc.py` 再次超过 `100 KB`，需要做仅结构、不改业务结果的治理。

## 本次边界
- 不修改 `Step2 / Step4 / Step5 / Step6` 的业务语义。
- 不修改 trunk gate、pair validation、segment_body 判定规则。
- 只做 repo 级治理文档同步与 Step2 纯 helper 拆分。

## 实际变更
- repo 级治理文档已把 `t01_data_preprocess` 与 `t02_junction_anchor` 共同登记为当前 `Active` 模块。
- `step2_segment_poc.py` 抽离出两个内部 helper 模块：
  - `step2_graph_primitives.py`
    - 承担 undirected 连通性、component、bridge 检测等纯图算法 helper
  - `step2_runtime_utils.py`
    - 承担 run id、out_root、progress callback 等运行时 helper
- `step2_support_utils.py`
  - 承担 shared support dataclass 与 endpoint priority helper
- `step2_segment_poc.py` 保留 pair validation、segment_body、same-stage arbitration 与 CLI/runner 主链编排。

## 结果
- `step2_segment_poc.py` 已回到 `100 KB` 阈值内，当前约 `98.3 KB`。
- 模块内与 repo 级治理口径重新对齐，不再存在“模块内 accepted / repo 级未登记 active”的冲突描述。

## 验证要求
- 必须重跑 Step2 相关 pytest。
- 必须重跑 `XXXS1-8 no-debug + freeze compare`，确认 active baseline 不漂移。

## 当前验证结果
- `py_compile` 已通过。
- Step2 / Skill / CLI 相关 pytest 当前通过 `120 passed`。
