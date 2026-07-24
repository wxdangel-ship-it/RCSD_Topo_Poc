# P05-JSG-PTO-P0 任务清单

## T001 合同与源事实

- [x] 同步项目级 source-of-truth。
- [x] 同步 P05 模块 source-of-truth 与 callable 接口。
- [x] 更新归档启动状态。

## T002 本体与 canonical contract

- [x] 实现 JSG 对象、枚举、校验和 signature。
- [x] 实现显式 loop、Terminal、Connector、Movement 合同。

## T003 Oracle truth builder

- [x] 读取冻结 51 Case manifest 和 T01/T05/T06/R2 lineage。
- [x] 生成 canonical JSG truth、覆盖统计、review 和 anomaly。
- [x] 验证多 THROUGH 不自动选择。

## T004 Evaluator

- [x] 实现 schema、ID、引用、方向、环岛、Connector、Movement hard gate。
- [x] 实现 serialize/deserialize 语义往返和 signature。

## T005 Compiler

- [x] 验证 `carrier_realization_ref` lineage/hash。
- [x] 编译到 R2 edit IR 并复用 materializer。
- [x] 使用 M0 evaluator 验证 Road/Node。

## T006 测试

- [x] 单元、破坏、确定性测试。
- [x] 全量 P05 回归测试（72/72）。

## T007 正式验收

- [x] 运行 51 Case run A。
- [x] 运行 51 Case run B。
- [x] 完成 signature、GIS、性能和证据审计。
- [x] 写入 `validation_summary.md` 和最终 go/no-go。
