# T01 任务清单

## 已完成基线
- [x] working Nodes / Roads 初始化前移到模块开始阶段
- [x] 后续业务判断统一切换到 `grade_2 / kind_2`
- [x] 环岛预处理接入 working bootstrap
- [x] 环岛 mainnode 保护接入 generic refresh
- [x] `XXXS` Skill v1.0 freeze baseline 已建立

## 本轮任务
- [x] 统一 node 输入约束为 `closed_con in {2,3}`
- [x] 统一排除 `road_kind = 1` 的封闭式道路
- [x] 接入 `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
- [x] 接入 `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- [x] 补充 `closed_con / road_kind` 使用审计文档
- [x] 补充 distance gate 集成文档
- [x] 完成 `XXXS` 官方回归与 freeze compare
- [ ] 若与现有 freeze 不一致，生成 candidate baseline 包并等待确认

## 后续待办
- [ ] 根据本轮 compare 结果决定是否更新 freeze baseline
- [ ] 继续完善大规模运行时的 low-memory / perf 收敛
- [ ] 继续补充更完整的 GIS 视觉验收与 case 审计能力
