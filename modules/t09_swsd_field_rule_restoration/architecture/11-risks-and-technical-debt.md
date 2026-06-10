# 11 Risks And Technical Debt

## 1. 当前风险

- RCSD Laneinfo 和轨迹通行证据尚未接入，Step3 当前只能基于 SWSD 证据投影 F-RCSD restriction。
- `partially_prohibited` 暂不自动投影为 F-RCSD 全 Arm 禁行，可能低估局部限制。
- 混源 F-RCSD Arm 依赖 T06 relation 的完整性，relation 缺失会导致 Step3 跳过。
- arrow 证据只能作为现场证据和冲突审计，不能替代 restriction。

## 2. 当前技术债

- T09 当前没有 repo 官方 CLI 主 runner。
- Step3 输入证据包已有脚本入口，但主业务运行仍依赖 callable。
- F-RCSD `RoadNextRoad` 生成仍在后续模块或后续迭代中处理。

## 3. 缓解方向

- 后续补充 RCSD Laneinfo / 轨迹证据时，应新增明确字段契约和质量要求。
- 若需要支持 partial restriction 投影，必须先定义 road-pair 到 F-RCSD 子承载的稳定映射。
- 若 T09 需要正式 CLI 或脚本入口，必须走入口治理并更新 `entrypoint-registry.md`。
