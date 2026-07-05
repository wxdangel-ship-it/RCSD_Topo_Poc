# T06 Root5 Step3 Top20 替换口径修正任务

- [ ] T001 更新 T06 模块源事实：`modules/t06_segment_fusion_precheck/SPEC.md`
- [ ] T002 更新 T06 接口契约：`modules/t06_segment_fusion_precheck/INTERFACE_CONTRACT.md`
- [ ] T003 更新 T06 架构事实：`modules/t06_segment_fusion_precheck/architecture/02-data-and-domain-model.md`
- [ ] T004 更新 T06 策略事实：`modules/t06_segment_fusion_precheck/architecture/03-solution-strategy.md`
- [ ] T005 更新 T06 质量要求：`modules/t06_segment_fusion_precheck/architecture/05-quality-requirements.md`
- [ ] T006 调整 Step2 RCSDSegment required junction / buffer hard gate 实现：`src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_extraction.py`
- [ ] T007 调整未替换归因中候选但未被目标 Segment 消费的 RCSDRoad 处理：`src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_unreplaced_attribution.py`
- [ ] T008 补充 T06 单元测试：`tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction.py`
- [ ] T009 补充未替换归因单元测试：`tests/modules/t06_segment_fusion_precheck/test_rcsd_unreplaced_attribution.py`
- [ ] T010 跑 T06 单元测试并记录结果
- [ ] T011 跑 `1206914_1257213` Segment 回归，输出收益/未落地清单
- [ ] T012 跑 `1885118` 基线对比，确认业务效果无回退
- [ ] T013 跑 T10 6 case 回归，确认业务效果无回退
- [ ] T014 汇总已修改 / 已验证 / 待确认
