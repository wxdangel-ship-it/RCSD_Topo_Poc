# Requirements checklist

- [x] 产品：准确性/安全性优先，GO不等于训练完成
- [x] 架构：冻结骨架、同模型、同推理证据、Dataset-P1唯一标签合同
- [x] 研发：P05内部callable，无新入口，无T01–T12实现修改
- [x] 测试：eligible/context、局部失败、分母、泄漏和整图门
- [x] QA：lineage、双跑、GIS、资源、体量和入口审计
- [x] Movement=0，T07=DRIVEZONE_ONLY，T06 inference=0
