# T01 任务清单

## 1. 当前轮次
- 名称：`hierarchical boundary fix before poc closeout`
- 性质：POC visual audit 问题修复与 case 级审计补强

## 2. 本轮编码任务

### 2.1 Step4 / Step5 层级边界修复
- [x] 新增历史 validated pair 端点 mainnode 收集逻辑
- [x] 为当前轮构建 cumulative hard-stop boundary set
- [x] 在 pair candidate 搜索阶段接入历史边界阻断
- [x] 在 `segment_body` component 收敛阶段接入历史边界阻断
- [x] 为 Step4 输出 `historical_boundary_nodes.geojson`
- [x] 为 Step5 输出 `historical_boundary_nodes.geojson`
- [x] 明确并实现：`mainnodeid = NULL` 的单点语义路口若命中当前轮输入规则，必须进入 `seed / terminate` 且不得再被当前轮 `through` 吞掉

### 2.2 Step4 错误构出修复
- [x] 复现 `STEP4:792579__55225234`
- [x] 修复其跨越 `763111` 的错误行为
- [x] 输出 case 级证据，证明该 case 已被历史边界中断

### 2.3 Step2 / Step4 未构出 case 审计
- [x] 审计 `784901__502866811`
- [x] 审计 `785324__502866811`
- [x] 审计 `784901__40237259`
- [x] 审计 `788837__784901`
- [x] 审计 `40237227__785217`
- [x] 审计 `55225313__785217`
- [x] 生成 `target_case_audit.json`

### 2.4 Step5 视觉问题收敛
- [x] 让 Step5A / Step5B terminate / hard-stop 纳入历史高等级边界
- [x] 保持 Step5A / Step5B 之间不刷新属性
- [x] 确认旧的错误跨级 through/terminate 结果不再进入 merged validated

### 2.5 外网验证
- [x] 重跑外网 `XXXS` Step4
- [x] 重跑外网 `XXXS` Step5
- [x] 复核 target cases 的最新状态

## 3. 当前待确认项
- [ ] `784901__502866811` 在 Step2 中仍为 `candidate -> no_valid_trunk`，后续是否需要专门扩展 trunk 规则，需要业务确认
- [ ] Step4 中若某端点在 residual graph 上被 `through` 消化，是否应继续保守不构出，还是在未来轮次专门提级处理，仍需确认
- [ ] Step5A 在 `XXXS` 上当前没有 validated pair，这是否符合优先轮业务预期，仍需确认

## 4. 明确不在本轮实现
- [ ] POC closeout / baseline handoff
- [ ] 启动 Step6
- [ ] 多轮一键执行总编排收尾
- [ ] 重写 Step1 / Step2 核心算法
