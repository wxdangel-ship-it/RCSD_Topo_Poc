# 第二部分 T09 通行规则恢复页组归档说明

## 归档状态

本组页面作为第二部分 T09 模块阶段性草稿归档，用于承接 T01 / T06 的 F-RCSD 输出，说明如何基于 SWSD 侧有限证据理解现实世界通行限制，并将推导出的规则映射到 F-RCSD。

## 页面定位

本组页面用于说明：

1. 现实世界通行限制并非只有单一字段来源，而是包括禁止通行标志、地面车道箭头、提前左转 / 提前右转等特殊通道。
2. SWSD 保存的是经过生产工艺压缩后的有限证据，不等于完整现场通行真值。
3. T09 需要基于 Restriction、Laneinfo 和特殊通道证据，按优先级逆向推导现场可能的 Arm 级和 Road 级通行规则。
4. 推导出的规则落到 F-RCSD 时，需要结合 T06 的承载关系与当前可用数据条件，明确当前可稳定恢复的范围和未闭环边界。

## 归档页面

| 页码 | 页面名称 | 归档图片 | 原始图片 |
|---|---|---|---|
| 第 15 页 | 现实世界的路口通行限制：三类规则来源与不同作用范围 | `docs/presentations/project-report-2026/image-drafts/archive/page-15-t09-traffic-restriction-rule-sources-accepted-draft-20260710.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月10日 09_54_25 (1).png` |
| 第 16 页 | SWSD 如何表达现实通行限制：可用证据与工艺隐患 | `docs/presentations/project-report-2026/image-drafts/archive/page-16-t09-swsd-evidence-and-process-loss-accepted-draft-20260710.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月10日 09_54_25 (2).png` |
| 第 17 页 | 基于 SWSD 有限证据，逆向推导现场可能的通行规则 | `docs/presentations/project-report-2026/image-drafts/archive/page-17-t09-infer-traffic-rules-from-limited-evidence-accepted-draft-20260710.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月10日 09_54_25 (3).png` |
| 第 18 页 | 将推导出的通行规则映射到 F-RCSD，并明确当前验证边界 | `docs/presentations/project-report-2026/image-drafts/archive/page-18-t09-map-rules-to-frcsd-validation-boundary-accepted-draft-20260710.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月10日 09_54_25 (4).png` |

## 核心表达

T09 不是简单复制 SWSD 字段，而是利用 Restriction、Laneinfo 和特殊通道证据，按优先级反推现场最可能的通行规则；落到 F-RCSD 时，还必须结合 T06 的替换承载关系与当前数据验证能力，区分可稳定恢复范围和未闭环风险。

## 后续待补

1. Restriction、Laneinfo、提前左转 / 提前右转的真实 Case 图。
2. 冲突裁决示例中的真实审计证据。
3. F-RCSD 映射后的 restriction 投影示例。
4. 当前可稳定恢复与尚未闭环边界的真实统计指标。
5. 与 T06 replaced / retained_swsd / 混合承载状态之间的传导案例。
