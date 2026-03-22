# T01 计划

## 当前阶段
- `Step5C adaptive barrier fallback fix`

## 本轮目标
1. 将 `Step5C` 从“历史 endpoint 机械继承 = terminate + hard-stop”修正为 adaptive barrier fallback。
2. 在 `Step5C` 内显式实现：
   - `rolling endpoint pool`
   - `protected hard-stop set`
   - `demotable endpoint set`
   - `actual terminate barriers`
3. 保持 `Step5A / Step5B` strict，不把 adaptive barrier 语义回灌到更早 staged 轮次。
4. 用 `XXXS5` 定点验证 `997356__39546395`，至少把阻塞原因从 terminate rigidity 推进到真实剩余阻塞。
5. 对当前活动 freeze baseline 的 `XXXS` 做 compare；若不一致，只输出差异报告，不更新 freeze。
6. 若 `XXXS5` 通过目视确认，则将其冻结入新的活动五样例套件，并逐样例 compare 验证。

## 本轮边界
- 不重写 `Step2`、`Step4`、`Step5A`、`Step5B` 主逻辑。
- 不放松 50m trunk / side gates。
- 不放松当前双向构段输入过滤：
  - `closed_con in {2,3}`
  - `road_kind != 1`
- 不把 `kind_2 = 1` 作为 `Step5C` current-input 字段筛选条件直接放开。
- 不 silently 更新当前活动五样例 freeze baseline。

## 实施顺序
1. 在 `Step5C` staged runner 内补齐 adaptive barrier 三集合 helper 与审计输出。
2. 调整 `Step5C` phase input，解耦 `rolling endpoint pool` 与 `actual terminate barrier`。
3. 同步修正 `Step1` 搜索内核，使已 demote 的 rolling endpoint 可继续作为 through，而不是仅因 seed 身份被卡死。
4. 补充 `Step5C helper / staged integration / Step1 through` 防回退测试。
5. 更新 `spec / plan / tasks / README / INTERFACE_CONTRACT / history` 文档。
6. 重跑 `XXXS5` 做定点审计，并对活动五样例套件逐样例 compare。

## Step6 segment-level aggregation and semantic audit POC
- 目标：消费最新 Step1–Step5C refreshed `nodes / roads`，聚合生成 `segment.geojson`、`inner_nodes.geojson`、`segment_error.geojson`，并按错误类型拆分输出子图层。
- 输入：人工显式传入 latest refreshed `nodes` / `roads`，不硬编码旧 run 目录。
- 核心语义：
  - segment 聚合只按非空 `roads.segmentid`
  - 语义路口统一使用 `working_mainnodeid`，为空回退 node `id`
  - `pair_nodes / junc_nodes / inner_nodes` 均基于语义路口组
- 反查规则：
  - 若两端 `pair_nodes` 的 `grade_2` 均为 `1`，则将 segment 级 `s_grade` 轻调整为 `"0-0双"`
  - 若 `s_grade = "0-0双"` 的 segment 中间仍出现 `grade_2 = 1 且 kind_2 = 4` 的 `junc_nodes`，输出到 `segment_error.geojson` 与 `segment_error_grade_kind_conflict.geojson`
  - 若同一 `segmentid` 下出现多值 `s_grade`，输出到 `segment_error.geojson` 与 `segment_error_s_grade_conflict.geojson`
- 边界：
  - 不回改 `Step1–Step5C`
  - 不重新做构段搜索
  - 不使用原始 `grade / kind`
