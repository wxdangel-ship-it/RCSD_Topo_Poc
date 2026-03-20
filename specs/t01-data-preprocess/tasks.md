# T01 任务清单

## 1. 当前轮次
- 名称：`Step5A/Step5B staged residual graph segment construction`
- 性质：POC / 双阶段 residual graph 编排与统一回写

## 2. 本轮编码任务

### 2.1 Step5A 输入编排
- [x] 从 Step4 refreshed `nodes.geojson / roads.geojson` 读取输入
- [x] 剔除历史已有非空 `segmentid` 的 road
- [x] 按 Step5A 节点规则生成 seed / terminate

### 2.2 Step5A 构段
- [x] 复用现有 pair / segment 内核运行 `STEP5A`
- [x] 输出 Step5A candidate / validated / rejected / trunk / segment_body / residual

### 2.3 Step5B 输入编排
- [x] 在 Step5A 工作图基础上剔除 Step5A 新 `segment_body` road
- [x] 不刷新属性，直接使用原始 Step4 refreshed `grade_2 / kind_2 / closed_con`
- [x] 按 Step5B 节点规则生成 residual graph 上的 seed / terminate

### 2.4 Step5B 构段
- [x] 复用现有 pair / segment 内核运行 `STEP5B`
- [x] 输出 Step5B candidate / validated / rejected / trunk / segment_body / residual

### 2.5 Step5 merged 与统一刷新
- [x] 合并 Step5A / Step5B validated pair
- [x] 合并 Step5A / Step5B segment_body / residual 审查图层
- [x] 统一刷新 Node：
  - 端点保持当前值
  - 单一 segment 内部 `-1 / 1`
  - 右转专用道侧向 `3 / 1`
  - 多进多出 `3 / 2048`
- [x] 统一刷新 Road：
  - 历史已有值保持不动
  - 本轮新 segment_body road 写入 `s_grade = "0-2双"`

### 2.6 输出与审计
- [x] 输出 `step5_summary.json`
- [x] 输出 `step5_mainnode_refresh_table.csv`
- [x] 输出 `nodes_step5_refreshed.geojson / roads_step5_refreshed.geojson`
- [x] 同时保留链式输入同名文件 `nodes.geojson / roads.geojson`

### 2.7 测试与验证
- [x] 补最小 pytest 覆盖 Step5A / Step5B 双阶段编排
- [x] 覆盖 Step5A 新 segment road 不参与 Step5B
- [x] 覆盖 Step5A / Step5B 之间不刷新属性
- [x] 覆盖 Step5 输出 `3 / 2048` 只作为未来 Step6 候选
- [x] 在外网 `XXXS` 上完成实跑

## 3. 本轮待确认项
- [ ] Step5B 仍可能重新遇到 Step5A pair 端点在 residual graph 上残留的情况；后续是否需要额外竞争抑制，还需要结合更大切片确认
- [ ] `through_collapsed_corridor` 在多轮场景下是否继续保留为正式 trunk 模式，需要后续业务确认

## 4. 明确不在本轮实现
- [ ] 启动 Step6
- [ ] 重写 Step1 / Step2 核心算法
- [ ] 完整 Step3 语义归并
- [ ] 多轮闭环
- [ ] 单向 Segment 阶段
