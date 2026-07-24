# P13-P0 实施计划

## specify

- 冻结candidate-set scorer目标、数据角色、5-fold合同和GO/NO-GO门；
- R1候选与candidate signature保持不变；
- truth只能在feature freeze后进入训练标签。

## plan

1. 校验R1正式Run B、P12R与Scheme-A baseline输入hash；
2. 重放R1 Phase 1，生成truth-free object/candidate/geometry feature；
3. 冻结feature schema、rows、signature和Case fold；
4. label-only join P12R/R1 Oracle，形成candidate multi-label dataset；
5. 实现fold-local transform、set scorer、训练、阈值和拒识；
6. 执行3 seeds × 5 folds并保存checkpoint/score/decision；
7. 重放access硬门；其余Review与candidate reachability只用于label-only安全评价，
   不得成为推理mask；随后验证fallback和terminal安全门；
8. 完成专项测试、正式双跑、完整P05回归、资源/体量/hash审计；
9. 同步P05模块级源事实并输出正式decision。

## implement边界

- 只新增P05内部源码、测试、P13 SpecKit和P05模块文档；
- 不回填P12R/P12R-R1主审计；
- 不修改T01–T12或项目正式入口；
- 不提交或推送Git。
