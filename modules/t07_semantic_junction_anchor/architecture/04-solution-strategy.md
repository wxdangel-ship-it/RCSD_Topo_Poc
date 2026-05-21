# 04 Solution Strategy

## 主策略

1. 读取 `nodes / DriveZone / RCSDIntersection`，严格校验字段、CRS 与 geometry。
2. 将空间输入统一到 `EPSG:3857`。
3. 按 `mainnodeid` 组装语义路口；空 `mainnodeid` 退化为 singleton。
4. 识别代表 node；多节点组要求 `id == mainnodeid`。
5. Step1 按代表 node `kind_2` 过滤处理范围。
6. Step1 对处理范围内语义路口执行 `DriveZone` intersects/touches 判定。
7. Step2 仅对 `has_evd = yes` 的语义路口执行 `RCSDIntersection` 判定。
8. Step2 先形成 provisional `yes / no / fail1`，再做 `fail2` 反向包含覆盖。
9. 输出只包含 `nodes`、语义路口级 summary、audit、perf 与 node error 工件。

## 分层建议

- `semantic_junctions.py`：语义路口组装、代表 node 识别。
- `step1_has_evd.py`：Step1 DriveZone gate。
- `step2_anchor_recognition.py`：Step2 RCSDIntersection 判定。
- `outputs.py`：summary、audit、perf 与 vector 输出。
- `runner.py`：组合 runner。

## 失败策略

- 业务 `no` 只表达空间未命中。
- 执行失败包括字段缺失、CRS 缺失、不可投影、geometry 缺失。
- 代表 node 缺失是数据结构问题，必须审计，不得 fallback。
- 非处理 `kind_2` 是业务跳过，稳定写为 `NULL`。
