# P05-Scheme-A-P2-P3-P3 验证摘要

## 1. 结论

正式判定：
`P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`。

本阶段证明 `ADVANCE_RIGHT access_valid=false` 可以作为独立、无真值泄漏的
推理期硬安全资格，彻底消除 Review 自动接受；但现有 202 维表征仍稳定误导剩余
可靠 target，当前 scorer 继续保持 NO-GO。

## 2. 正式证据

- Run A：`p05_scheme_a_p2_p3_p3_audit_20260723_02`
- Run B：`p05_scheme_a_p2_p3_p3_audit_20260723_03`
- 规范化 signature：
  `0f7d4ee09835afb408efa986f54ed980ca941484a3ca62c7f3805f8d684fa97c`
- Run B `reference_run_match=true`

## 3. 核心结果

- 6,275/6,275 eligible group 与冻结 Segment 清单精确匹配。
- 40个 `access_valid=false` 全部为
  `ADVANCE_RIGHT + REVIEW_FALLBACK`，非 Review 命中为0。
- 三seed共120条Review decision全部硬回退。
- Review auto：`0/0/0`。
- 最终accepted wrong：`1/1/0`。
- 每seed终态：49 `LEGAL` + 2 `EXPECTED_FAIL`。
- context auto、context effective non-KEEP、非目标级联、closure conflict、
  Node mismatch、repair、silent fix和骨架mutation均为0。

残余对象三个seed均选择错误`USE_RCSD`，score margin为
`13.58/12.87/15.99`。三个held-out训练域各取20个最近邻，60/60均为
`USE_RCSD`真值，说明当前表征把该对象稳定映射到错误区域；下一步不是增加同一
模型epoch或调当前threshold，而是先建设T06之前可用的新关系/共享上下文表征。

## 4. 验证

- 专项测试：6 passed。
- 完整P05回归：216 passed。
- Run A/B wall：约107.23s/130.52s。
- peak RSS：约1.82GB；GPU=0。
- model training、threshold change、T06 inference、Movement和geometry
  read/write均为0。
- 所有新增源码/测试文件均低于100KB；未新增CLI、script、T10 stage、
  `__main__.py`或Makefile target。

口径修正前Run 01仅作诊断，不作为正式结论来源。

## 5. 后续重解释

P2-P3-P4 已证明唯一残余 false-use 的旧 `KEEP_SWSD` 真值由 Dataset-P1 之前的
context-only Junction 闭包污染产生。P3 工件和当时审计结果不删除，但
“新表征必需”不再是当前结论；当前应以 P4 的 scope-first 真值重基线为准。
