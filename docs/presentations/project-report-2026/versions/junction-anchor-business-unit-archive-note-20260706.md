# 第二部分路口锚定业务单元页组归档说明

## 归档状态

本组页面初步完成，作为第二部分“路口锚定业务单元”阶段性草稿归档。

## 页面定位

本组页面承接第 5 页 T08 数据预处理与结构修复，进入第二部分的第一个核心业务单元：路口锚定。该业务单元用于说明 T07 / T03 / T04 / T05 如何将 SWSD 语义路口与 RCSD 中可解释的现实世界路口基点建立稳定关系，并为后续 T06 Segment 替换提供可消费 Relation。

## 整体表达原则

1. 不重复第 3 页总体业务流程。
2. 以业务问题和模块职责展开，不做单纯工具或代码说明。
3. 除 SWSD、RCSD、T07、T03、T04、T05、T06、Relation 等必要模块 / 专有名词外，页面业务描述统一使用中文。
4. 页面风格保持与第一部分归档页一致：白底、深红标题、红色模块编号、浅灰卡片边框、克制技术汇报风格。
5. 本组页面中预留的真实 Case 或指标图位，后续由 Codex 使用内网真实结果补齐。

## 归档页面

| 页码 | 页面名称 | 归档图片 | 原始图片 |
|---|---|---|---|
| 第 6 页 | 路口锚定：在异源数据间建立稳定现实世界基点 | `docs/presentations/project-report-2026/image-drafts/archive/page-06-junction-anchor-business-problem-accepted-draft-20260706.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月6日 16_06_42 (1).png` |
| 第 7 页 | T07 / T03 / T04：路口锚定证据生产机制 | `docs/presentations/project-report-2026/image-drafts/archive/page-07-t07-t03-t04-evidence-production-accepted-draft-20260706.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月6日 16_06_50 (2).png` |
| 第 8 页 | T05：Relation 统一发布与图可消费质量门 | `docs/presentations/project-report-2026/image-drafts/archive/page-08-t05-relation-publish-consumable-gate-accepted-draft-20260706.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月6日 16_06_58 (3).png` |
| 第 9 页 | 补充：路口锚定业务单元总览 | `docs/presentations/project-report-2026/image-drafts/archive/page-09-junction-anchor-business-unit-overview-accepted-draft-20260706.png` | `C:\Users\admin\Downloads\ChatGPT Image 2026年7月6日 16_07_04 (4) (1).png` |

## 页面要点

### 第 6 页：路口锚定业务问题与场景分治

本页说明为什么不能直接通过几何相交或最近点匹配完成 SWSD 与 RCSD 路口关系，而需要先建立现实世界层面的稳定锚点。

核心表达：路口锚定的目标不是“找一个最近的 RCSD 节点”，而是把 SWSD 语义路口与 RCSD 中可解释的现实路口基点建立关系。

### 第 7 页：T07 / T03 / T04 证据生产机制

本页说明 T07 / T03 / T04 三类模块如何面向不同路口形态生产锚定证据。三者职责不同，但目标一致：把不同形态的 SWSD 语义路口转换为 T05 可消费的锚定证据。

核心表达：T07 / T03 / T04 不是三个割裂算法，而是路口锚定业务单元中的三类证据生产机制。

### 第 8 页：T05 Relation 发布与图可消费质量门

本页说明 T07 / T03 / T04 只负责生产证据，真正决定是否能进入替换系统的是 T05 的 Relation 发布和图可消费判断。

核心表达：T05 的目标不是“生成 Relation 记录”，而是发布可被 T06 替换审查系统消费的、稳定的 SWSD-RCSD 语义路口关系。

### 第 9 页：路口锚定业务单元总览 / 小结

本页把第 6 页、第 7 页、第 8 页串联起来，说明从场景识别、证据生产到 Relation 发布与质量门控，如何形成一个可审计、可追溯的路口锚定业务单元。

核心表达：路口锚定业务单元将异源数据理解、证据生产、Relation 发布与质量门控串联起来，为后续 T06 替换和全链路质量闭环提供稳定基础。

## 后续待补

1. 内网真实 Case 图。
2. T05 质量漏斗真实统计数据。
3. graph consumable / graph unconsumable 的真实指标。
4. 每类阻断原因对应的真实数量。
5. 与 T06 替换结果之间的传导案例。

## 视觉规范

- 保持红灰正式技术汇报风格；
- 除 SWSD、RCSD、T07、T03、T04、T05、T06、Relation 等必要专有名词外，业务说明统一使用中文；
- 顶部说明只保留文字，不使用额外图标；
- 页面编号保持右下角或页面角标统一；
- 文字内容后续可根据真实指标再精简。
