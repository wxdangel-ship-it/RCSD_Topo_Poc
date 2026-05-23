# T01 Step2 kind_2=128 Performance Fix - Tasks

- [x] T1: 阅读 T01 accepted baseline 与 Step2 trunk 实现，确认变更边界。
- [x] T2: 增加 trunk path search budget 结构与枚举中止机制。
- [x] T3: 在复杂 `kind_2 = 128` pair 上启用预算限制并返回可审计 reject reason。
- [x] T4: 在 Step2 summary 中增加预算超限统计。
- [x] T5: 增加单元测试覆盖预算超限。
- [x] T6: 运行相关 pytest。
- [x] T7: 用 XS1 pair 43 和 XS2 前 100 pair 做性能回归。
- [x] T8: 增加 `kind2_128_local_corridor` 局部 port corridor 策略，避免复杂路口内部全局追溯。
- [x] T9: 增加局部 corridor validated / rejected 单元测试，并用 XS1 复杂热点区间做性能对比。
