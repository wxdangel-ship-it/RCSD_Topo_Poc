# 06 风险与技术债

## 1. 业务风险

- T05 是最终关系主表发布点，若对同一 target 发布多条 success relation，会直接污染 T06 Segment 替换。
- `many_target_to_one_base` 可作为非阻断审计保留，但 `one_target_to_many_base` 与重复 success target 必须阻断。
- T10 feedback 若被误用为独立 relation 来源，会绕过 T07/T03/T04 的路口锚定证据。

## 2. 数据风险

- 旧 T03 evidence 可能缺少 Phase 2 场景分流字段，需要 backfill 兼容；当前 T03 evidence 字段完整时不应默认补齐。
- T04 fallback 场景字段缺失时必须从 accepted layer、summary、audit 或 case-level audit 补读，补读失败不得 silent fallback。
- RCSDLaneinfo 与更丰富的轨迹通行证据尚未进入 T05，Phase 2 relation 仍依赖当前空间与 relation evidence。

## 3. 结构债

Phase 2 `phase2_runner.py` 承载了较多决策、junctionization、cardinality 和输出职责。后续拆分时应保持 callable 契约、测试和输出一致性，优先按只读 relation、grouping、split、cardinality 和输出模块拆分。

## 4. 治理缺口

T05 需要持续维护“Phase 1 只做 surface、Phase 2 才做 relation/junctionization”的边界。新增脚本或入口前必须同步入口登记，避免内网实验脚本被误读为官方主 runner。
