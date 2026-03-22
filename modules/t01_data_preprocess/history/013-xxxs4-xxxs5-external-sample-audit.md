# 013 - XXXS4 / XXXS5 外网补充样例审计

## 1. 背景
- 2026-03-21，外网测试数据目录新增两组补充验证样例：
  - `E:\TestData\POC_Data\first_layer_road_net_v0\XXXS4`
  - `E:\TestData\POC_Data\first_layer_road_net_v0\XXXS5`
- 这两组样例当前用于补充验证，不属于当前活动三样例基线。
- 用户给定的样例目标：
  - `XXXS4`：侧向平行路应纳入 `Segment`
  - `XXXS5`：长距离 `Segment` 应构建成功

## 2. 执行方式
- 运行环境：
  - WSL
  - `uv run -- python -m rcsd_topo_poc t01-run-skill-v1`
- 使用默认官方入口：
  - `configs/t01_data_preprocess/step1_pair_s2.json`
  - `formway_mode=strict`
  - `debug=true`
- 本轮外网运行产物：
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs4_external_check/`
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs5_external_check/`

## 3. XXXS4 审计结果

### 3.1 样例目标
- 目标：验证侧向平行路可被纳入最终 `Segment`，而不是全部退回 residual。

### 3.2 实际运行结果
- official runner 可完整跑通，无运行时异常。
- 汇总结果：
  - `validated_pairs_skill_v1.csv`：`42`
  - `segment_body_membership_skill_v1.csv`：`100`
  - `trunk_membership_skill_v1.csv`：`100`
- 关键现象：
  - 最终 `segment_body_membership` 与 `trunk_membership` 数量完全相等。
  - 全样例没有任何 pair 出现 `segment_body` 超出 `trunk` 的额外 road。
  - 说明当前实现没有把任何侧向并入路正式保留进最终 `Segment`。

### 3.3 直接证据
- 在 `Step2` 中，pair `S2:950362__953936` 的 non-trunk component：
  - road ids：`529159693`、`611944611`
  - `side_access_distance_m = 160.97789758980204`
  - `decision_reason = side_access_distance_exceeded`
- 上述两条 road 在最终 `roads.geojson` 中：
  - `segmentid = null`
  - `s_grade = null`
- 这表明该侧向平行分支被打回 residual，没有纳入最终 `Segment`。

### 3.4 结论
- `XXXS4` 当前未通过。
- 若该样例口径已确认属于正式目标，则现实现阶段存在业务问题，后续需要针对侧向平行路纳入策略继续分析与修复。

## 4. XXXS5 审计结果

### 4.1 样例目标
- 目标：验证长距离 `Segment` 可以被成功构建，而不是因距离或 staged runner 轮次问题被错误拒绝。

### 4.2 实际运行结果
- official runner 可完整跑通，无运行时异常。
- 汇总结果：
  - `validated_pairs_skill_v1.csv`：`55`
  - `segment_body_membership_skill_v1.csv`：`95`
  - `trunk_membership_skill_v1.csv`：`94`
- 关键现象：
  - 最终 `segment_body_membership` 大于 `trunk_membership`，说明样例内存在 trunk 之外被正式保留的 `Segment` road。
  - 存在多条长距离 segment 成功构建，例如：
    - `S2:997356__1029576`：`6` 条 road，累计长度约 `768.185m`
    - `S2:1026960__39546395`：`3` 条 road，累计长度约 `700.770m`
    - `S2:997356__1019747`：`7` 条 road，累计长度约 `690.009m`

### 4.3 直接证据
- `STEP5A:612301465__613762500` 出现 1 条额外 `segment_body` road：
  - extra road id：`629657215`
  - `side_access_distance_m = 44.202782188946905`
  - `decision_reason = segment_body`
- 该 road 在最终 `roads.geojson` 中：
  - `segmentid = 612301465_613762500`
  - `s_grade = 0-2双`

### 4.4 结论
- `XXXS5` 当前通过。
- 长距离 `Segment` 构建能力在该样例上已得到直接验证。

## 5. 总结
- `XXXS4`
  - 当前存在问题
  - 样例目标“侧向平行路纳入 Segment”未满足
- `XXXS5`
  - 当前通过
  - 样例目标“长距离 Segment 构建成功”已满足
- 处理建议：
  - 暂不把 `XXXS4 / XXXS5` 纳入活动基线
  - 后续若要扩展活动回归样例，建议先修复并复测 `XXXS4`
  - `XXXS5` 可直接作为后续性能优化与语义回归的补充外网样例
