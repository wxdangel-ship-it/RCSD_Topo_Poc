# Phase 0 验收摘要

## 状态

`PHASE_0_COMPLETE_READY_FOR_T005`

T001–T004 已完成：合同哈希已冻结，既有 64D/12D 特征已按真实向量类型完成逐维
来源审计，Step1 RC 证据保持 DriveZone-only，feature/label/test 三重隔离与 105 条 blind
test 不可读门禁已建立。没有实现新网络、没有训练、没有读取剩余 105 条冻结测试标签，
也没有修改 T01–T12 正式实现或接口。

## 已验证

- 合同冻结文件：`contracts/contract-freeze.json`；三个源合同 SHA-256 已由自动测试复算。
- 特征审计：`object64 / node_candidate64 / road_bundle64 / member12` 共 204 个有类型维度；
  分类合计为 raw 22、derived_geometry 84、candidate_metadata 12、forbidden 86。
- 关键阻断：历史 Node candidate 与 Road bundle 的 64D 编号存在语义复用；新链路必须
  显式携带候选向量类型，无类型 `candidate64` 直接拒绝。
- Step1 可见索引固定为 `0,1,2,3,13,14,15,21,22,23,24`；其中 SWSD 是查询对象，
  唯一 RC 证据为 DriveZone，RCSD Node/Road/RCSDIntersection 和候选向量不可见。
- blind-test seal：测试总数 106；历史 schema discovery quarantine 1；剩余 blind 105；
  仅冻结源 split hash 与剩余身份聚合 hash，T029 前读取接口恒定阻断。
- Python 写前体量检查：两个新增文件均从 0 byte 开始；三个历史 60KiB 观察线文件保持
  只读，未触及正式 CLI、入口或接口。
- 定向合同测试：`14 passed`。
- 相邻 Stage1、joint store、T05 anchor dataset 回归：合计 `29 passed`。
- 测试环境：WSL，Python 3.10.12，torch 2.9.1+cu128；Windows 系统 Python 3.12
  因不符合项目版本且缺少 torch，仅记录为环境阻断，不用于正式验证。
- `git diff --check` 通过。

## GIS / 拓扑边界

本阶段不读取或改写 GIS 数据，因此不产生 CRS 转换、拓扑修复或几何输出。T005 必须建立
城市对象仓的 CRS/输入 manifest，T019 必须验证拓扑一致性、几何语义、silent fix=0 和
可追溯 materializer。该验证义务未被本阶段门禁替代。

## 下一执行门

允许进入 T005–T008：实现城市对象仓和完整 `JunctionResultPrediction` 的随机初始化
free-run 骨架。仍禁止训练；T009–T020 的阶段防火墙、结构 decoder、materializer 与安全
ledger 未完成前，不得启动正式 canary。

## 当前不代表

- 不代表网络 accuracy、自动覆盖或零危险门已经通过。
- 不代表可以读取冻结测试。
- 不代表可以恢复 Segment、AdvanceRight 或 Movement。
- 不代表 P05 已接入正式主链或生产。
- 不代表历史 64D/12D 特征已经被批准为新网络主表示。
