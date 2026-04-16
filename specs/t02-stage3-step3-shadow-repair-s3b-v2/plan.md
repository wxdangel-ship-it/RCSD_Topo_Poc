# plan

## 允许触碰
- src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step3_shadow_frontier.py（新增 helper）
- src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py 中与 Step3 legal space / shadow export 直接相关的最小片段

## 不触碰
- stage3_step5_foreign_model.py
- stage3_step6_* 正式几何策略
- stage3_step7_acceptance.py
- stage3_review_facts.py
- contract / manifest / 官方 CLI

## shadow path 开关
- 通过 step3_shadow_frontier_config 和 step3_shadow_export_root 两个 kw-only 参数显式开启。
- 默认调用不传参时，formal Step3 结果保持原样。

## 验证方式
- baseline：运行 pytest tests/modules/t02_junction_anchor/test_anchor61_baseline.py -q
- shadow：对 Anchor61 61 case 逐个运行 shadow comparison；保留 12 个代表样本的 baseline/shadow 导出，其余 case 只提取 summary。
