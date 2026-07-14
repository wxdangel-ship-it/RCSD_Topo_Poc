# Research: T06 六用例性能回退诊断

## 1. 三套基线口径

| 口径 | 用途 | 判定方式 |
|---|---|---|
| 当前版本业务基线 | 冻结优化前业务结果 | 优化后结构化正式业务差异为 0 |
| 当前版本性能/内存基线 | 量化本轮实际收益与资源风险 | 对比 wall/CPU/peak RSS |
| 已冻结正式性能基线 | 最终性能目标 | 各用例和六例合计均不得更慢 |

历史优化候选的 Step3 六例 `415.858s` 只作为 stretch/reference，不替代已冻结正式目标 `489.920s`。

## 2. 已冻结 Step3 目标

| Case | Step3 seconds |
|---|---:|
| `1885118` | 170.562194 |
| `605415675` | 69.407（最终按 stage JSON） |
| `609214532` | 136.368（最终按 stage JSON） |
| `706247` | 51.197（最终按 stage JSON） |
| `74155468` | 29.287（最终按 stage JSON） |
| `991176` | 33.100（最终按 stage JSON） |
| **Total** | **489.920（最终按 stage JSON）** |

## 3. 当前回退证据

- 当前提交：`c26b760e6d0e945db6e2fc44885841e136b4a78e`。
- 相同冻结输入的 `1885118` Step3 独立运行：3 次完整 Step3，共 `382.81s`，折算约 `127.60s/次`，peak RSS `689652 KB`。
- 当前正常 T10 调用会触发 4 次完整 Step3，实测 `506.742s`，折算约 `126.69s/次`。
- 对比冻结 `170.562s`，主要回退来自完整 pipeline 重放次数增加，不是数据规模增长。

## 4. 动态热点

ownership 微基准约 `22.73s`，cProfile 约 `21.90s`：

- ownership build/write：约 `13.17s`；
- scored candidates：约 `7.74s`；
- coverage ratio：约 `6.90s`；
- Shapely buffer：约 `5.72s / 60187 calls`；
- 三组 feature triplet 写出：约 `7.37s`；
- vector read：约 `6.16s`；JSON：约 `3.42s`。

construction refresh 微基准约 `12.63s`。

## 5. 静态调用链结论

1. 每次 `_run_step3` 都构建 ownership 与 construction；随后 `_run_surface` 又刷新二者。
2. postplan baseline、candidate、topology-safe hard-gate 等验证轮次重复执行正式发布路径。
3. topology rebuild 会清空 coverage/read caches，使同一 Step3 生命周期内的内容寻址复用失效。
4. ownership relation 字段仅在 ownership 模块内写入/读取，未发现 final topology hard-gate 以这些发布文件作为决策输入；因此候选验证轮可在内存中保持相同计算结果，并把正式发布延后到最终选定状态。
5. 当前 `suppress_feature_json_outputs` 只抑制部分 feature JSON，不能阻止 ownership/construction refresh 的 GPKG/CSV/JSON 重写。

## 6. 架构合理性判断

- 合理：Step2 决定计划、Step3 执行、surface/final topology 对执行结果做审计与受控回退。
- 不合理：验证候选与发布最终正式产物共用同一个“完整运行并落盘”路径，导致验证次数线性放大 CPU、I/O 与内存峰值。
- 不合理：不可变输入、geometry digest 和只读索引生命周期短于 Step3 pipeline 生命周期。
- 优化原则：区分 `validation state` 与 `publish state`，候选轮仍执行全部业务计算与审计，但只在最终 state 发布 ownership/construction/正式 triplets；缓存必须有内容 key、有容量边界、可在最终发布后释放。

## 7. 待补充实跑证据

- 当前提交六例 Step1/2、Step3、总 wall/CPU/RSS。
- 当前提交六例结构化业务基线。
- 优化候选 `1885118` 等价与性能结果。
- 最终六例逐例和合计验收表。
