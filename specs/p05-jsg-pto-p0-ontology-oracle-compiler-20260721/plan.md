# P05-JSG-PTO-P0 实施计划

## 1. 设计原则

1. 先语义、后 carrier、再 RoadGraph。
2. truth 转换与 compiler 分层；JSG truth 不直接携带最终 GPKG 二进制。
3. 未知与冲突显式化；`REVIEW` 是合法业务状态，不是失败修复手段。
4. 复用 R2 edit IR/materializer，禁止复制 T06 业务规则。
5. 所有正式运行不可变，第二轮用于确定性复核。

## 2. 实施阶段

### Phase A：合同与源事实

- 建立本 SpecKit、数据模型、输出合同和验收清单。
- 同步项目级与 P05 模块级 source-of-truth。
- 将归档状态从“暂缓”更新为“已授权启动”，保留其历史归档角色。

### Phase B：JSG 本体与 truth builder

- 实现强类型对象、状态、canonical serialization 和 signature。
- 从冻结 Case manifest 提取 T01/T05/T06/R2 lineage。
- 构建 Junction/Segment/Relation/Connector/Terminal/Movement 和 carrier realization。
- 输出 anomaly、review 与对象覆盖清单。

### Phase C：evaluator 与 compiler

- 实现 schema、引用、方向、环岛、多贯穿、Connector、Movement hard validation。
- 实现 canonical roundtrip 与 deterministic signature。
- 将 JSG carrier realization 编译为现有 R2 edit IR，并调用现有 materializer。
- 使用 M0 evaluator 验证 T06 Road/Node hard gate。

### Phase D：测试与真实数据验收

- 完成合成单元测试、回归测试和破坏测试。
- 运行 51 Case run A、run B。
- 对比 signature、资源和逐 Case结果，形成 validation summary 与 go/no-go。

## 3. 模块边界

计划新增：

- `jsg_models.py`：对象、枚举、配置与 canonical contract。
- `jsg_truth.py`：truth/lineage 转换。
- `jsg_evaluation.py`：语义和结构评价。
- `jsg_compiler.py`：JSG 到 R2 IR/物化。
- `jsg_p0.py`：模块 callable 编排和不可变 run。

不新增独立执行入口；调用面只从 `rcsd_topo_poc.modules.p05_neural_road_generation` 暴露。

## 4. GIS 验证

- CRS：输入与 truth CRS 缺失或冲突 hard fail，不隐式重投影。
- 拓扑：对象 ID、引用、Road 端点、有向连通显式验证，不 silent fix。
- 几何：JSG access/carrier 关联必须可解释；RoadGraph 继续使用 M0 几何指标。
- 审计：输入、参数、输出、环境与 hash 可定位。
- 性能：逐 Case wall/CPU、全量 wall/CPU、RSS、对象/边数可验证。

## 5. 风险控制

- T01 字段不足以证明细粒度类型时保留 raw evidence 和 `REVIEW`，不新增强规则。
- 51 Case 无真实 loop 时只通过 schema/合成测试证明表示支持，并在正式报告中标记零实例。
- R2 Oracle carrier 是 label-only 编译真值；任何未来候选/模型实验必须另建 P1 manifest 隔离。
- JSG 语义等价与 Road/Node 精确一致分别报告，避免把 carrier ID 一致误称为业务本体已泛化。
