# 06 风险与技术债

## 1. 业务风险

- 如果把 arrow 排除或 special carrier 当作强禁止证据，会产生错误 restriction。
- 如果同一 restriction id 下多组 link-pair 被折叠，会丢失 Movement 粒度证据。
- 如果 retained SWSD carrier fallback 不标记风险，T10 和人工审计会误以为该 carrier 来自正式 RCSD 替换。

## 2. 数据风险

- 当前缺少 RCSD Laneinfo 与轨迹通行证据，F-RCSD 通行能力恢复仍依赖 SWSD 现场证据和 T06 carrier 映射。
- T06 relation 缺失、F-RCSD Road/Node 缺失或 `source=2` carrier 范围不清，会阻断 Step3 restriction 投影。
- restriction / arrow 输入可能来自非空间表或局部切片，必须依赖 summary 和 text bundle manifest 定位来源。

## 3. 结构债

T09 需要同时维护 Step1/2 规则恢复和 Step3 F-RCSD 投影。后续若引入 RCSD Laneinfo 或轨迹证据，应先扩展 Evidence 模型和质量要求，不应直接改变 `fully_prohibited` 判定口径。

## 4. 治理缺口

Step3 输入证据包脚本只是证据提炼工具，不是主 runner。后续若新增正式入口，必须同步入口登记与 `INTERFACE_CONTRACT.md`。
