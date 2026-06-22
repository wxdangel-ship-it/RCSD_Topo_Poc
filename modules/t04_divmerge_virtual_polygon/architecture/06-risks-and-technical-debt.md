# 06 风险与技术债

## 1. 业务风险

- 复杂路口弱证据场景多，容易把 RCSD 数据存在误判为 RCSD 语义路口成立。
- `STEP4_REVIEW` 若被误读为失败或最终状态，会导致 baseline 解读偏差。
- `road_surface_fork + partial` relation handoff 若不在 T04/T05 收口，T06 可能在 Segment 阶段错误反推复杂路口基点。

## 2. 数据质量风险

- DivStripZone、DriveZone、RCSDRoad、RCSDNode 缺失或局部不一致时，T04 需要显式输出 fallback 或 reject，不能静默构面。
- 外部 T07/T03 relation 校验输入可能为空、非法 JSON 或缺 `features`，应按外部输入审计处理。
- road-only 与 SWSD-only 场景容易产生可视化上“像正确”的面，但缺少主证据时不能伪造 Reference Point。

## 3. 结构债

T04 代码存在业务主链与 full-input 编排层并行演化的特点。后续重构应继续保持 Step1-Step7 语义稳定，避免把 `full_input_*` 的运行便利性倒灌到业务规则。

## 4. 治理缺口

复杂路口属性修正长期应逐步移交 T08，T04 保持构面、relation evidence 和审计职责。T04/T03/T07 的 relation 共同进入 T05 后，应持续避免在 T06 再次解释路口关系。
