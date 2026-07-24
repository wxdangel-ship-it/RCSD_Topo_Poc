# P05-Scheme-A-P2-P2-P2-P0 验收摘要

## 1. 正式结论

`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`

现有允许在推理期使用的 truth-free 证据不足以在未知 Case 上同时满足零错误、完整 unsafe fallback 和两个 `>=0.50` 覆盖门。该结论不否定候选可达性、Node/RoadGraph 安全闭包或神经模型的离线排序价值，但禁止把当前证据和 probe 用于自动替换 SWSD。

## 2. 正式证据

- Run A：`outputs/_work/p05_neural_road_generation/p05_scheme_a_p2_p2_p2_p0_audit_20260723_02`
- Run B：`outputs/_work/p05_neural_road_generation/p05_scheme_a_p2_p2_p2_p0_audit_20260723_04`
- evidence signature：`fcfbafd042742a4de53a36dca330ba51e474dacb5a2833a6543aaf09ad15d824`
- determinism signature：`b04485a71f05df15d36135a3193edcf8db150855ae24878b435faead028142e3`
- Run B `reference_run_match=true`
- `_01` 为全局指标 group 对齐修正前的无效诊断运行；`_03` 为资源墙钟字段移出 determinism payload 前的无效重放运行。

## 3. 分母与泄漏门

- 51 Case、8,863 Segment、9 个三 base-seed 一致但错误的 proposal、40 Review、5 个固定 Case fold。
- 202 维 evidence；T07 `DRIVEZONE_ONLY` 为 51/51 Case，实际验证 93 个被 proposal/KEEP 使用的 Road artifact。
- T03/T04/T05/T06 model-input、truth feature、identifier feature、绝对坐标 feature、Movement candidate 均为 0。
- 9 个错误 proposal 与 40 Review 的 evidence vector 缺失均为 0。

## 4. Probe 结果

| probe | 参数量 | accepted wrong | 9 error 自动发布 | Review 自动发布 | 总体 coverage | USE coverage | unsafe recall | 通过 fold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LINEAR | 203 | 2 | 2 | 0 | 0.525217 | 0.741980 | 0.969169 | 1/5 |
| SHALLOW_MLP | 15,105 | 0 | 0 | 0 | 0.548686 | 0.755729 | 0.994191 | 0/5 |

浅层 MLP 的全局平均看似接近门槛，但门禁要求每个 held-out fold 同时通过。其部分 fold coverage 仅 `0.037594~0.465054`，另有 fold unsafe recall 低于 `1.0`，因此不能用全局平均掩盖跨 Case 不稳定。

## 5. Node/RoadGraph、资源与测试

- 两个 probe 均保持 49 `LEGAL + publish=true`、2 `EXPECTED_FAIL + publish=false`、unexpected failure=0。
- conditioned Node requirement conflict、target mismatch、payload conflict 均为 0；skeleton mutation=0、content repair=false、silent fix=false。
- 本阶段不执行坐标变换或几何修补；复用 hash 冻结且已通过 EPSG:3857 一致性检查的 P2-P1 candidate，新增 Road 证据只读取 `id/snodeid/enodeid` 有向属性，T07 anchor 只做 ID 覆盖统计。CRS、几何来源、输入 hash、参数、运行环境和输出均由 manifest/ledger 可追溯。
- Run B wall=`1054.755s`、peak RSS=`2470.453MB`、GPU memory=0，满足 6h/16GB/8GB 门。
- 新阶段与直接回归：`12 passed`。
- P05 全量：`174 passed, 1 failed`；唯一失败是既有 Dataset-P0 `_peak_rss_bytes()` 在当前 WSL 缺少可用 process-memory backend 时返回 0，与本阶段无关。
- P05 `src/` + `tests/` 共 146 个源码/测试文件，`>=60KiB=0`、`>=100KB=0`，最大仍为 `scheme_a_baseline.py` 58,135 bytes。

## 6. 后续边界

- 停止在本次 202 维证据、已见 held-out Case 和当前两个 probe 上继续加 epoch、扩模型或调阈值重报 GO。
- 当前只保留离线排序、Review 优先级和 RealityChangeClue 辅助价值。
- 后续若继续自动发布研究，必须引入真正新增且推理期可用的信息源，或另立独立预训练表征阶段并使用新的冻结 Case 验证；若要把当前 label-only 模块字段提升为 model input，必须先由用户二次确认并同步源事实。
