# T01 任务清单

## 1. Skill v1.0.0 已完成项
- [x] Step1 只输出 `pair_candidates`
- [x] Step2 固化为 `validated / rejected / trunk / segment_body / step3_residual`
- [x] Step2 `segment_body` 收敛为 pair-specific road body
- [x] Step2 强规则 A / B / C 固化
- [x] mirrored bidirectional case 纳入强规则
- [x] 修复右转专用道误纳入
- [x] 修复 `791711` T 型双向退出误追溯
- [x] trunk 支持双向 road 镜像最小闭环
- [x] trunk 支持 split-merge 混合通道
- [x] trunk 支持 semantic-node-group closure
- [x] `mainnodeid = NULL` 单点路口语义固化
- [x] 层级边界 / 历史高等级边界固化
- [x] Step4 residual graph 固化
- [x] Step5A / Step5B / Step5C staged residual graph 固化
- [x] 官方 end-to-end 入口 `t01-run-skill-v1`
- [x] freeze compare 入口 `t01-compare-freeze`
- [x] XXXS freeze baseline 轻量审计包
- [x] 内网测试三件套契约写入模块文档

## 2. 当前正式版构建任务
- [x] 收敛默认 `debug=false` 输出
- [x] 以 temp stage 目录减少默认无意义 I/O
- [x] 对 XXXS freeze baseline 做 compare PASS 校验
- [x] 输出性能 before / after / compare 产物
- [ ] 完成 repo 级治理文档与正式模块状态同步

## 3. 正式模块完整构建待办
- [ ] Step6
- [ ] 单向 Segment
- [ ] Step3 完整语义归并
- [ ] 完整多轮闭环治理
- [ ] 更深层图内存复用，减少阶段间内部临时序列化
- [ ] 正式模块化统一编排入口
- [ ] 更完整的测试 / 回归 / 验收体系
