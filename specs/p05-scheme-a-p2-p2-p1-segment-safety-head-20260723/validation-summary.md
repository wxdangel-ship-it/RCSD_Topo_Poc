# P05-Scheme-A-P2-P2-P1 验证总结

## 1. 正式结论

本阶段已完成，正式判定为 **`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`**。

独立 Segment safety/abstention head 已按批准口径完成训练和整图执行，但不能同时满足“错误接受为零”和“总体/`USE_RCSD` 覆盖均不低于 50%”。该结果不表示候选缺失或 RoadGraph 方案失败：候选可达性沿用 Dataset-P0 GO，Node 条件化闭包与每 seed 的 49+2 整图终态全部通过。

## 2. 正式证据

- 正式 Run A：`p05_scheme_a_p2_p2_p1_oof_20260723_03`
- 正式 Run B：`p05_scheme_a_p2_p2_p1_oof_20260723_04`
- 两轮 determinism signature 均为 `8fbb0e25e706ca4edc064fc39356f8d6f7c904dbb505372db178f8780a681742`。
- `safety_scores.jsonl`、`decisions.jsonl`、`evaluation.jsonl`、`effective_selections.jsonl` 文件 hash 分别一致；153 条 RoadGraph index 去除运行目录后完全一致，全部 RoadGraph 业务 signature 一致。
- `_01` 为 expected-failure Node 尚未接入 manifest 豁免时的中断训练工件；`_02` 为发现 fallback 后 Node QA 仍错误对比原始 truth 的被替代工件。两者均保留，不作为正式结论证据。

## 3. Safety Head 指标

模型为 410,786 参数的 Segment-only candidate-set safety head；输入为冻结 candidate/object/context feature 与三个 P2-P1 base OOF seed 的 score/agreement 统计。模型只能接受或回退，不能改选 candidate。

| safety seed | accepted wrong | precision | 总体覆盖 | USE 覆盖 | unsafe fallback recall | 稳定 false-use 自动发布 |
|---:|---:|---:|---:|---:|---:|---:|
| 101 | 5 | 0.998495 | 0.374817 | 0.431714 | 0.979893 | 4 |
| 103 | 0 | 1.000000 | 0.069841 | 0.066911 | 1.000000 | 0 |
| 107 | 4 | 0.998477 | 0.296288 | 0.380843 | 0.980786 | 4 |

40 个 Review 的自动发布始终为零。seed 103 证明极保守模型可以零错误，但总体和 USE 覆盖都只有约 7%；seed 101/107 提高覆盖后又放过稳定 false-use。因此没有 seed 同时通过零错误、precision=1、总体覆盖>=0.50、USE 覆盖>=0.50 和 unsafe recall=1.0。

## 4. Node 与 RoadGraph

- 每 seed：49 `LEGAL + publish=true`、2 `EXPECTED_FAIL + publish=false`、unexpected failure=0。
- effective Segment→Node requirement conflict=0、conditioned target mismatch=0、Node payload conflict=0。
- 原始 Node truth 与 fallback 后有效 Node carrier 的差异分别为 2,805/7,412/4,128；这是 Segment 回退后从 proposal Node 条件化为 T01/OMIT 的预期变化，不是业务错误。
- Junction fallback 每 seed 为 2，均由共享 carrier/内部拓扑影响触发；Segment fallback 仍保持逐 Segment 单元。
- skeleton mutation=0、content repair=false、silent fix=false、Movement candidate/decision/evaluation=0。

## 5. 泄漏、资源与治理

- 51 Case、8,863 Segment、5 outer fold、3 base seed、3 safety seed、40 Review 和 8 个稳定 false-use 分母精确。
- truth/ID/绝对坐标/Movement feature 计数均为零；每折 train/held-out Case 交集为零。
- Python 3.10.12、`torch 2.9.1+cpu`；正式训练约 80.4~80.8 秒，总 wall 约 198~204 秒，峰值 RSS 约 2.13GB，GPU 使用为零。
- CUDA wheel 下载两次因网络中断，故本阶段使用同版本官方 CPU wheel；没有修改 `pyproject.toml` 或 `uv.lock`。
- 专项测试：5 passed。完整 P05 回归：167 passed、1 failed；唯一失败为既有 `scheme_a_dataset_p0._peak_rss_bytes()` 在缺少 `psutil` 的 WSL 路径没有 POSIX fallback 而返回 0，本轮没有修改该历史模块。正式 P2-P2-P1 资源审计直接使用 `resource.getrusage`，数据有效。
- P05 `src/` + `tests/` 共 141 个源码/测试文件，`>=60KiB=0`、`>=100KB=0`；未新增 CLI、root script、`__main__.py`、Makefile target 或 T10 stage。

## 6. 后续边界

不得在已见 held-out Case 上继续调 risk threshold、增加 epoch 或扩大同一网络后重报 GO。若继续研究，应新立阶段验证“新增 truth-free 业务证据/更强预训练表征是否改善跨 Case 安全泛化”，或者明确把神经网络降级为离线排序和人工 review 辅助；任何下一阶段仍需用户另行授权。
