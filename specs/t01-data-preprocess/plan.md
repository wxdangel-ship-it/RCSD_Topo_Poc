# T01 计划

## 1. 当前阶段
- 阶段名：`hierarchical boundary fix before poc closeout`
- 阶段目标：
  - 修复 visual audit 暴露的 Step2 / Step4 / Step5 问题
  - 在 Step4 / Step5 中补齐层级边界硬停止逻辑
  - 在 Step2 trunk 判定中补齐双向 road 的最小闭环语义
  - 对指定 target cases 输出 case 级审计证据
  - 暂不进入分支收尾与 baseline handoff

## 2. 本轮要做
- 在 Step4 / Step5 中引入累计历史边界 mainnode 集合
- 在 Step2 trunk 判定中落实：
  - `direction = 0 / 1` 视为两条方向相反的可通行 road
  - 镜像往返同一组双向 road 可构成合法最小闭环
  - 正反路径局部共享双向 road、且共享段以相反方向通行时，也应视为同一合法最小闭环的一部分
- 让历史边界同时作用于：
  - pair candidate 搜索阶段
  - `segment_body` 收敛阶段
- 让历史边界同时进入当前轮 `seed / terminate`，而不是只做 `hard-stop`
- 对 Step5B 明确区分：
  - `S2 + Step4` 历史端点会回注入 `seed / terminate`
  - `Step5A` 当轮新端点只做 `hard-stop`
- 对以下 case 做定点审计与修复：
  - Step2：`784901__502866811`
  - Step4：`785324__502866811`
  - Step4：`784901__40237259`
  - Step4：`788837__784901`
  - Step4：`40237227__785217`
  - Step4：`55225313__785217`
  - Step4 错误 case：`792579__55225234`
- 在外网 `XXXS` 上重跑 Step4 / Step5 并输出新的审查结果

## 3. 本轮不做
- 不做 POC closeout / baseline handoff
- 不启动 Step6
- 不做多轮总编排一键执行收尾
- 不重写 Step1 / Step2 主算法

## 4. 本轮交付
- 文档更新：
  - `spec.md`
  - `tasks.md`
  - `README.md`
- 代码更新：
  - Step4 / Step5 层级边界逻辑
  - case 级审计输出
  - `historical_boundary_nodes.*`
- 外网 `XXXS` 新结果：
  - Step4 审查目录
  - Step5 审查目录
  - `target_case_audit.json`

## 5. 验证准则
- `STEP4:792579__55225234` 不再错误穿越 `763111`
- Step5A / Step5B 的 terminate / hard-stop 已纳入历史高等级边界
- target cases 全部给出“已修复 / 未修复但原因明确”的结果
- 已通过的 tighten 修复不回退
