# T01 任务清单

## 本轮排工
- [x] 以 spec-kit 方式为“文档一致性审计 + Step2 性能优化”立项
- [x] 识别正式文档与当前 T01 代码的主要冲突点
- [ ] 完成正式文档与 spec-kit 过程文档修订
- [ ] 将文档修订提交到 `main` 并推送

## 批次 A：正式文档一致性审计
- [x] 审计 `overview.md`
- [x] 审计 `06-accepted-baseline.md`
- [x] 审计 `INTERFACE_CONTRACT.md`
- [x] 审计 `README.md`
- [ ] 回写 `bootstrap node retyping`
- [ ] 回写 family-based refresh retyping
- [ ] 清除旧的泛化 `2048` 刷新叙述
- [ ] 明确当前 working bootstrap 阶段顺序

## 批次 B：spec-kit 过程文档重置
- [ ] 重写 `spec.md` 为本轮治理主题
- [ ] 重写 `plan.md` 为本轮治理计划
- [ ] 重写 `tasks.md` 为本轮任务状态

## 批次 C：main 收口与工作区清理
- [ ] 仅提交 T01 文档与 spec-kit 修订
- [ ] 推送到 `origin/main`
- [ ] 清理本地脏数据
- [ ] 确认 `git status --short` 为空
- [ ] 确认本地 `main` 与 `origin/main` 一致

## 批次 D：Step2 性能 / 内存审计
- [ ] 审计 Step2 主要热点函数
- [ ] 审计 Step2 中间对象与峰值内存来源
- [ ] 复盘内网死机可能的触发路径
- [ ] 形成优化点优先级清单

## 批次 E：Step2 优化实现
- [ ] 切独立优化分支
- [ ] 实施 Step2 性能 / 内存优化
- [ ] 跑相关单测
- [ ] 跑 `XXXS1-8`
- [ ] 确认业务效果不变

## 当前非回退基线
- [x] `XXXS1`
- [x] `XXXS2`
- [x] `XXXS3`
- [x] `XXXS4`
- [ ] `XXXS5`
- [x] `XXXS6`
- [x] `XXXS7`
- [x] `XXXS8`
