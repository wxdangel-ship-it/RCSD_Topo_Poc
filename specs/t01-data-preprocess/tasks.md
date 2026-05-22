# T01 任务清单

## 本轮排工
- [x] 以 spec-kit 方式为“文档一致性审计 + Step2 性能优化”立项
- [x] 识别正式文档与当前 T01 代码的主要冲突点
- [x] 完成正式文档与 spec-kit 过程文档修订
- [x] 将文档修订提交到 `main` 并推送
- [x] 确认 `kind_2 = 128` 在双向 Segment 构建中允许穿越
- [x] 明确本轮只做 `kind_2 = 128` 穿越审计，不改变 `seed / terminate / hard-stop / through_node_ids` 语义

## 批次 A：正式文档一致性审计
- [x] 审计 `overview.md`
- [x] 审计 `06-accepted-baseline.md`
- [x] 审计 `INTERFACE_CONTRACT.md`
- [x] 审计 `README.md`
- [x] 回写 `bootstrap node retyping`
- [x] 回写 family-based refresh retyping
- [x] 清除旧的泛化 `2048` 刷新叙述
- [x] 明确当前 working bootstrap 阶段顺序

## 批次 B：spec-kit 过程文档重置
- [x] 重写 `spec.md` 为本轮治理主题
- [x] 重写 `plan.md` 为本轮治理计划
- [x] 重写 `tasks.md` 为本轮任务状态

## 批次 C：main 收口与工作区清理
- [x] 仅提交 T01 文档与 spec-kit 修订
- [x] 推送到 `origin/main`
- [x] 清理本地脏数据
- [x] 确认 `git status --short` 为空
- [x] 确认本地 `main` 与 `origin/main` 一致

## 批次 D：Step2 性能 / 内存审计
- [x] 审计 Step2 主要热点函数
- [x] 审计 Step2 中间对象与峰值内存来源
- [x] 复盘内网死机可能的触发路径
- [x] 形成优化点优先级清单

## 批次 E：Step2 优化实现
- [x] 切独立优化分支
- [x] 实施 Step2 性能 / 内存优化
- [x] 跑相关单测
- [x] 跑 `XXXS1-8`
- [x] 确认业务效果不变

## 批次 F：`kind_2 = 128` 双向穿越审计
- [x] Step1 `PairRecord` 增加 `kind_2_128_*` 审计字段
- [x] Step1 `pair_candidates.csv / pair_table.csv / pair_summary.json` 输出穿越审计
- [x] Step2 validation support_info 透传 `kind_2_128_*`
- [x] Step2 `validated_pairs.csv / rejected_pair_candidates.csv / pair_validation_table.csv / segment_summary.json` 输出穿越统计
- [x] 正式 source-of-truth 文档补入双向穿越审计口径
- [x] 增加定向单测
- [ ] 等待内网全量回传后评估 candidate 规模、8000 慢簇与 `dual_carriageway_separation_exceeded` 的相关性

## 当前非回退基线
- [x] `XXXS1`
- [x] `XXXS2`
- [x] `XXXS3`
- [x] `XXXS4`
- [x] `XXXS5`
- [x] `XXXS6`
- [x] `XXXS7`
- [x] `XXXS8`
