# 第5页归档说明：T08 SWSD Road / Node 字段标准化与路口结构修复

## 归档信息

- 页面名称：第5页：T08：SWSD Road / Node 字段标准化与路口结构修复
- 归档图片：`docs/presentations/project-report-2026/image-drafts/archive/page-05-t08-swsd-road-node-standardization-accepted-draft-20260706.png`
- 原始图片：`C:\Users\admin\Downloads\ChatGPT Image 2026年7月6日 10_36_30.png`
- 归档日期：2026-07-06

## 页面定位

本页属于项目汇报 PPT 第二部分“业务模块问题定位与质量承接”的开篇页，用于说明 T08 在主链中的前置数据治理价值。第 3 页已展示总体业务流程，因此本页不再重复流程图，而是直接进入 T08 模块的问题定位。

## 核心表达

T08 不直接执行 RCSD 替换，也不生产路口 Relation，而是增强 SWSD Road / Node 的信息含量，修复基础结构错误，为后续 T01 Segment 构建、T03/T04 路口锚定、T05 Relation 发布和 T06 替换审查提供稳定的事实输入。

## 页面结构

本页只保留两个业务模块：

1. SWSD Road / Node 字段问题
   - 说明 Road PatchID、Road kind、Node kind_2 / grade_2、环岛 mainnode 等字段和结构信息的业务价值。
   - PatchID 与 RCSD、Patch 内 RC 数据配套，理论上可提升后续业务质量；当前因 RCSD 与 PatchID 不同源，暂未深度使用。
   - Road kind 是原始 SWSD 重要属性，具备后续扩展价值；当前主要用于少量异常处理，暂未深度使用。
   - Node kind / grade 初始化为 kind_2 / grade_2，为后续模块提供稳定结构判断字段。
   - 环岛 mainnode 聚合用于降低后续路口锚定和 Segment 处理复杂度。

2. 路口类型与复杂结构修复
   - 说明 T 型路口、无意义交叉路口、分歧 / 合流、连续分合流、复杂路口等 SWSD Node 类型错误对后续质量的影响。
   - T 型路口修复对路口锚定质量影响较大。
   - 去除无意义交叉路口类型，例如 SC 变 DC 等场景，可减少非必要路口锚定要求，提高路段替换能力。
   - Node kind 增加环岛和复杂路口表达，尤其是连续分歧 / 合流等复杂场景，简化后续业务处理难度。
   - 对持续发现的 Node kind 错误，后续可继续追加质量修复策略，并保留人工介入确认能力。

## 页面风格

本页按第一部分归档页风格调整为红灰技术汇报风格：

- 白底；
- 深红主标题；
- 红色模块编号；
- 浅灰卡片边框；
- 克制、正式、技术型；
- 与前面 PPT 页面视觉保持一致。

## 预留内容

页面中预留“内网真实 Case 位置”，后续由 Codex 补齐真实案例图。建议优先补充：

- T 型路口修复前后案例；
- 无意义交叉路口类型去除案例；
- 连续分歧 / 合流复杂路口聚合案例；
- RCSDIntersection 一对多处理案例。

## 页面结论

T08 不直接替换道路，而是增强 SWSD 信息含量、修复基础结构错误，为后续 T01 / T03 / T04 / T05 / T06 的判断提供稳定事实基础。
