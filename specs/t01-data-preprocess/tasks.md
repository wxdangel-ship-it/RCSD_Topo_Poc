# T01 任务清单

## 已完成基线
- [x] working Nodes / Roads 初始化前移到模块开始阶段
- [x] 后续业务判断统一切换到 `grade_2 / kind_2`
- [x] 环岛预处理接入 working bootstrap
- [x] 环岛 mainnode 保护接入 generic refresh
- [x] `XXXS` Skill v1.0 freeze baseline 已建立

## 本轮任务
- [x] 审计当前 A200 `debug / no-debug` 阶段级性能瓶颈
- [x] 确认 `Step2` validated 流程存在重复 `_refine_segment_roads(...)`
- [x] 确认 trunk validation 中存在按 pair 重复全图扫描 `context.directed`
- [x] 去除 validated 流程中的重复 `_refine_segment_roads(...)`
- [x] 将 trunk validation 的 directed adjacency 构造改为仅遍历 `allowed_road_ids`
- [x] 保持 `Step2 / Step4 / Step5` 共用同一优化后的双向构段内核
- [x] 补充性能防回退测试
- [x] 完成 `XXXS / XXXS2 / XXXS3` 官方回归与逐样例 baseline compare

## 后续待办
- [ ] 在内网 A200 上复测本轮性能优化后的 `debug / no-debug` 差异
- [ ] 继续收敛 `Step2` 主计算热点，优先评估 path enumeration / validation 内核
- [ ] 评估 `Step4 / Step5` staged runner 的 working-layer I/O 是否需要进一步降本
- [ ] 继续补充更完整的 GIS 视觉验收与 case 审计能力
