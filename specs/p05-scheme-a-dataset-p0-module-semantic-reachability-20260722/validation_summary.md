# P05-Scheme-A-Dataset-P0 验收摘要

## 1. 正式结论

`P05-Scheme-A-Dataset-P0` 已完成，结论为 **`P05_SCHEME_A_DATASET_P0_GO`**。该结论证明现有 `E:\TestData\POC_Data` Case 能形成模块职责正确、候选可达且安全可审计的离线训练合同；不授权 scorer 训练、在线 proposal 或生产接入。

正式证据：

- Run A：`outputs/_work/p05_neural_road_generation/p05_scheme_a_dataset_p0_20260722_04`
- Run B：`outputs/_work/p05_neural_road_generation/p05_scheme_a_dataset_p0_20260722_05`
- 确定性：`outputs/_work/p05_neural_road_generation/p05_scheme_a_dataset_p0_determinism_20260722_02.json`

## 2. 数据与角色

| 指标 | 结果 |
|---|---:|
| M0 sample | 741 |
| module artifact | 520 |
| task target | 11,856 |
| RoadGraph Case | 51 |
| Segment | 8,863 |
| 可用 Segment | 8,823 |
| mask/归因 Segment | 40 |

T01 只承担 SWSD Segment 冻结骨架与 fallback；T07 固定 `DRIVEZONE_ONLY`；T03/T04/T05 为 label-only 中间监督；T06 Step3 Road/Node 为最终主标签；T09、T11、T10 分别只承担下游验证、经重跑确认的修正来源和数据组织/split。T01 RCSD label、骨架 mutation、truth input/derived candidate、Movement candidate/decision/evaluation 均为0。

## 3. 候选可达性

| 指标 | Run A / Run B |
|---|---:|
| `USE_RCSD` 非 T01 Road | `2190/2190 = 1.0` |
| 可用 Segment Road | `8823/8823 = 1.0` |
| T06 final Road | `23224/23224 = 1.0` |
| T06 final Node | `27553/27553 = 1.0` |
| Segment Road + final Node 联合 exact | `1.0` |

历史 P2-P0 的 `USE_RCSD retention=0.165753` 是其受限 carrier bundle 的联合安全保留率，不是候选可达率。Dataset-P0 证明正确 RCSD carrier 已存在于非 T01 truth-free proposal 中，因此“补更多 Case”或“让 T01 产生 RCSD”不是当前阻塞项。

## 4. 安全、GIS 与资源

- RoadGraph：49 `LEGAL` + 2 `EXPECTED_FAIL`；新增失败=0。
- `content_repair=false`、`silent_fix=false`、`relaxation=false`。
- CRS：仅 `EPSG:3857`；冲突=0，重复 truth ID=0，未分类 candidate source=0。
- Run A：wall `5.158833s`，peak RSS `281,288,704 bytes`，无需 GPU。
- Run B：wall `5.123055s`，peak RSS `295,366,656 bytes`，无需 GPU。
- module role、sample、artifact、task、candidate source、Segment reachability、Case reachability 七类内容 signature 完全一致；Gate 与 decision 一致。

## 5. 测试与治理

- Dataset-P0 单元/破坏测试：11 passed。
- P05 完整回归：156 passed。
- Python compile/import：通过。
- P05 `src/` 与 `tests/` 源码/测试共125个，`>=100KB=0`、`>=60KiB=0`；本阶段最大新文件 `scheme_a_dataset_p0.py=51,752 bytes`。
- 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage；未修改 T01–T12 正式实现；未提交或推送 Git。

## 6. 下一阶段边界

Dataset-P0 已消除“候选集合里没有正确 carrier”的阻塞。下一阶段如获独立授权，应在本次冻结高召回候选上重新设计 object-conditioned scorer 和整图 compatibility/anomaly calibration；历史 strategy replay 的在线成本仍须由轻量或增量 proposal generator 独立解决。Dataset-P0 GO 不能替代 scorer OOF、在线性能和生产安全验收。
