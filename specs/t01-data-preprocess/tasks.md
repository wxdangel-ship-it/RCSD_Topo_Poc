# T01 任务清单

## 1. POC 已完成项

### 1.1 首轮语义与实现
- [x] Step1 明确收敛为 `pair_candidates`
- [x] Step2 明确收敛为：
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- [x] Step2 `segment_body` 收紧为 pair-specific road body
- [x] 弱规则不再在 Step2 中硬删，统一进入 `step3_residual`

### 1.2 Step2 强规则与已闭环修复
- [x] 强规则 A：non-trunk component 触达其他 terminate（非 A/B）即剔除
- [x] 强规则 B：non-trunk component 吃到其他 validated trunk 即剔除
- [x] 强规则 C：过渡路口“同向进入 + 同向退出”停止追溯
- [x] mirrored bidirectional case 纳入强规则 C
- [x] 修复右转专用道误纳入问题
- [x] 修复 `791711` T 型双向退出误追溯问题

### 1.3 trunk 语义补齐
- [x] 双向 road 视为两条方向相反的可通行 road
- [x] 支持双向 road 镜像最小闭环
- [x] 支持 split-merge 混合通道
- [x] trunk 闭环从纯几何闭环扩展为 semantic-node-group closure
- [x] trunk 以语义路口为单元，支持 `mainnode group` 与 `mainnodeid = NULL` 单点路口

### 1.4 层级边界与输入约束
- [x] 更低等级轮次在更高等级历史路口中断
- [x] 历史高等级边界同时作用于 pair 搜索与 segment 收敛
- [x] 历史高等级边界按 accepted 口径进入 seed / terminate / hard-stop
- [x] `mainnodeid = NULL` 单点路口按独立语义路口进入 seed / terminate
- [x] 当前轮合法 seed / terminate 节点不再被 through 吞掉

### 1.5 residual graph 多轮构段
- [x] 首轮完成后输出 refreshed `Node / Road`
- [x] Step4 residual graph 构段
- [x] Step5A / Step5B staged residual graph 构段
- [x] Step5C 将 `kind_2=1` 纳入补充轮
- [x] 已有 `segmentid` road 在后续轮次工作图中剔除
- [x] Step5A / Step5B / Step5C 之间只剔除新 `segment_body` road，不刷新属性
- [x] Step5 完成后统一刷新 `grade_2 / kind_2 / s_grade / segmentid`

## 2. POC 收尾交付
- [x] accepted baseline 业务语义已写入文档
- [x] 语义修正对齐说明已单独沉淀到 history 文档
- [x] POC closeout handoff 文档已完成
- [x] 当前推荐入口、推荐输入基线、推荐输出基线已明确

## 3. 正式模块完整构建待办
- [ ] Step6
- [ ] 单向 Segment
- [ ] Step3 完整语义归并
- [ ] 完整多轮闭环治理
- [ ] 正式模块化统一编排入口
- [ ] 一步到位端到端执行器
- [ ] 更完整的测试 / 回归 / 验收体系
- [ ] 更明确的 visual audit / machine audit 联动标准

## 4. 不再归入 POC 任务
- [ ] 新增额外试验轮次
- [ ] 继续追加无明确 acceptance 的试验性业务口径
- [ ] 在 POC 任务清单中混入正式模块完整构建任务
