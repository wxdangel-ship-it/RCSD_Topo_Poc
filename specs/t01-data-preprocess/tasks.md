# T01 任务清单

## 已完成基线
- [x] working Nodes / Roads 初始化前移到模块开始阶段
- [x] 后续业务判断统一切换到 `grade_2 / kind_2`
- [x] 环岛预处理接入 working bootstrap
- [x] 环岛 mainnode 保护接入 generic refresh
- [x] 活动 freeze baseline 已切换到五样例套件：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS5`

## 本轮任务
- [x] 将 `Step5C` 定位为 final fallback 轮，不改 `Step5A / Step5B` strict 语义
- [x] 实现 `Step5C rolling endpoint pool`
- [x] 实现 `Step5C protected hard-stop set`，当前只保留环岛 mainnode
- [x] 实现 `Step5C demotable endpoint set`
- [x] 实现 `Step5C actual terminate barrier` 重判
- [x] 追加 `Step5C` 三集合审计输出与 `endpoint_demote_audit`
- [x] 追加 `target_pair_audit_997356__39546395.json`
- [x] 补充 `Step5C helper / staged integration / Step1 through` 防回退测试
- [x] 重跑 `XXXS5` 并确认 `997356__39546395` 的新状态
- [x] 将 `XXXS5` 冻结入活动基线
- [x] 重跑 `XXXS / XXXS2 / XXXS3 / XXXS4 / XXXS5` freeze compare，确认与活动 baseline 一致

## 定点验收
- `XXXS5 / 997356__39546395`
  - 理想目标：在 `Step5C` 成功进入 candidate / validated / segment
  - 可接受目标：若仍未构出，必须证明剩余阻塞已不再属于 terminate rigidity

## 后续待办
- [ ] 评估是否需要把 `Step5C adaptive barrier` 审计 helper 再抽到共享层
