# T01 任务清单

## 1. 当前轮次
- 名称：`Step5A/Step5B/Step5C staged residual graph segment construction`
- 性质：在现有 Step5 staged residual graph 上扩展第三阶段并完成统一刷新

## 2. 本轮编码任务

### 2.1 Step5C 编排扩展
- [x] 在 Step5 内部新增 `Step5C`
- [x] 保持单一 Step5 入口，不新增额外外层执行入口
- [x] 保持 Step5A / Step5B / Step5C 之间不刷新属性
- [x] 让 Step5C 工作图继续剔除：
  - 历史已有 `segmentid` road
  - `Step5A` 新 `segment_body` road
  - `Step5B` 新 `segment_body` road

### 2.2 Step5C 输入规则
- [x] 实现 Step5C 输入集合：
  - `closed_con in {1,2}`
  - `grade_2 in {1,2,3}`
  - `kind_2 in {1,4,2048}`
- [x] 保持历史边界回注入口径：
  - `S2 + Step4` 端点进入 Step5C `seed / terminate`
  - `Step5A / Step5B` 当轮新端点仅进入 Step5C `hard-stop`

### 2.3 Step5 输出与刷新
- [x] 输出 `step5c_*` 审查结果
- [x] 让 merged 结果同时合并 `Step5A / Step5B / Step5C`
- [x] 让 Step5 refreshed `Node / Road` 同时累计三阶段结果
- [x] 保持本轮新 `segment_body` road 写入：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`

### 2.4 外网验证
- [x] 重跑外网 `XXXS` Step5
- [x] 验证 Step5C 可接收 `kind_2=1` 节点
- [x] 验证 merged / refreshed 结果包含 Step5C 贡献

### 2.5 trunk 全局语义修复
- [x] 将 trunk 判定从“纯几何闭环”扩展为“semantic-node-group closure 也可成立”
- [x] 明确 trunk 以语义路口为单元，支持 `mainnode group` 与 `mainnodeid = NULL` 单 node 路口
- [x] 补充 synthetic case，覆盖“语义闭合但物理几何不开环”的合法 trunk

## 3. 当前待确认项
- [ ] Step5C 是否还需要在未来继续细分优先轮 / 收尾轮，当前先不拆阶段
- [ ] `kind_2=1` 节点在更大切片上的命中比例与误检风险，仍需继续验证

## 4. 明确不在本轮实现
- [ ] POC closeout / baseline handoff
- [ ] 启动 Step6
- [ ] 多轮一键执行总编排收尾
- [ ] 重写 Step1 / Step2 核心算法
