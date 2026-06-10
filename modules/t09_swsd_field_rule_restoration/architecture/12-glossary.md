# 12 Glossary

- **Arm**：SWSD 语义路口的道路方向业务单元。
- **Movement**：同一语义路口内 `from_arm -> to_arm` 的候选通行方向。
- **Carrier Universe**：承载某个 Movement 的候选 road-pair 集合。
- **Restriction**：显式禁止通行证据，通常表达 `inLinkID -> outLinkID`。
- **Arrow**：Laneinfo 地面箭头证据，用于支持、排除、冲突或人工复核。
- **Complete Arrow Exclusion**：完整箭头排布未支持某 Movement 的现场证据，不单独生成禁行。
- **Special Carrier**：提前左转、提前右转、辅路提右等不经过普通中心路口的现场承载证据。
- **Restored Field Rule**：T09 从证据中还原出的 SWSD Movement 级现场规则。
- **F-RCSD restriction**：T09 Step3 输出到 F-RCSD 的 `LinkID -> outLinkID` 禁止通行关系。
