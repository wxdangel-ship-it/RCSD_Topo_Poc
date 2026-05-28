# 12 Glossary

- `semantic junction`：由 `nodes.mainnodeid` 聚合形成的语义路口；空 `mainnodeid` 时退化为单 node 语义路口。
- `representative node`：承载 `has_evd / is_anchor / anchor_reason` 写值的语义路口代表 node。
- `kind_2`：T07 当前唯一正式类型判断字段。
- `has_evd`：语义路口是否有道路面资料，值域为 `yes / no / NULL`。
- `is_anchor`：语义路口是否锚定到 `RCSDIntersection`，值域为 `yes / no / fail1 / fail2 / NULL`。
- `anchor_reason`：特殊锚定原因，当前值域为 `t / NULL`；`kind_2 = 64 / 128` 暂不在 T07 Step2 内产生专项原因。
- `fail1`：同一语义路口组命中多个 `RCSDIntersection` 的冲突。
- `fail2`：同一个 `RCSDIntersection` 对应多个语义路口的冲突，优先级高于 `fail1`。
- `intersection_match_all.geojson`：T05 Phase2 输出的 SWSD-RCSD 语义路口 relation 主表，字段为 `target_id / base_id / status / level / is_highway`。
- `intersection_match_tool7.geojson`：T07 Step3 输出的 T05 relation 子集，只包含候选 SWSD 语义路口、T05 relation 成功且输入 RCSD 中存在 `base_id` 的记录。
- `Segment-free`：T07 不读取、不生成、不统计 T01 `segment`。
