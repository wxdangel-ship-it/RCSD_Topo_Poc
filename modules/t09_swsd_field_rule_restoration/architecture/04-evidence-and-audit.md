# 04 证据与审计

## 1. 审计目标

T09 必须让每条 restored rule 和 F-RCSD restriction 都能回溯到 SWSD Movement、restriction / arrow / carrier evidence、T06 relation 和 F-RCSD carrier。无证据、证据不足、拓扑不可达和方向不适用不能被写成禁止。

## 2. Step1/2 证据

| 证据 | 业务用途 |
|---|---|
| `t09_swsd_arms.*` | SWSD Arm 结构和风险标记。 |
| `t09_arm_movements.*` | Movement 候选、carrier universe 和状态。 |
| `t09_evidence_items.*` | restriction / arrow / special carrier 证据项。 |
| `t09_restored_field_rules.*` | Movement 级规则还原结果。 |
| `t09_swsd_field_rule_restoration_summary.json` | 输入、输出、证据计数、CRS、QA 和性能。 |

## 3. Step3 证据

| 证据 | 业务用途 |
|---|---|
| `frcsd_restriction.gpkg/csv/json` | F-RCSD 禁止通行关系。 |
| `t09_step3_frcsd_restriction_summary.json` | carrier 映射、输出计数、跳过原因和风险统计。 |

## 4. Text Bundle 证据

Step3 输入证据包导出脚本用于内外网轻量传递局部 SWSD、T08 Tool7/8、T06 F-RCSD 和 Segment relation 证据。该脚本不替代 T09 主业务 runner，解包后仍由 callable 执行业务规则。

## 5. 风险审计

retained SWSD seed fallback、混源 carrier、缺 Segment relation、缺 F-RCSD Road/Node、几何无法构造、arrow/restriction 冲突和 special carrier displacement 都必须进入 risk flags 或 summary 跳过原因。
