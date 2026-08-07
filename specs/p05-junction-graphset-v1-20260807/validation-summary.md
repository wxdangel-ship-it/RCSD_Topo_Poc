# Phase 0–1 验收摘要

## 状态

`PHASE_1_COMPLETE_READY_FOR_T009`

T001–T008 已完成：Phase 0 合同与隔离门保持不变；Phase 1 已建立城市级单次解析 store、
定向业务依赖切片、完整预测合同、packed 变长 batch、candidate binding 和安全锁定的随机
free-run。没有训练、没有读取剩余 105 条冻结测试身份/标签，也没有修改 T01–T12 正式
实现或接口。

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
- 城市 store：同 city/合同只解析一次；重复请求返回相同 store；变化合同阻断；空间窗口
  外 required dependency 可达；对象引用不复制；顺序确定；CRS 不一致阻断。
- GIS：非法几何原样保留并计数，silent fix=0；证据 SHA-256 在唯一 GIS 遍历中同步计算，
  不做整文件 hash 后再次解析。
- 完整输出：surface、anchor state、Node/Road、main anchor、Node equivalence、Road break、
  topology、quality/review、confidence 与 ABSTAIN 均进入同一 schema。
- candidate binding：越界对象、未知 plan、后续修改锚定或打断方案均阻断。
- packed batch：空/变长样本和空 batch 可运行，21D token/8D edge 不按 Case 数填充。
- 4,288 条 development-only 身份的空证据合同 free-run：合法 `4,288`、ABSTAIN
  `4,288`、非 ABSTAIN `0`、非法 `0`、blind access `0`；随机骨架 737 参数且安全锁定。
- Phase 0–1 与历史相邻回归合计：`44 passed`。
- 测试环境：WSL，Python 3.10.12，torch 2.9.1+cu128；Windows 系统 Python 3.12
  因不符合项目版本且缺少 torch，仅记录为环境阻断，不用于正式验证。
- `git diff --check` 通过。

## GIS / 拓扑边界

Phase 1 仅用合成 GIS fixture 验证读取、CRS、对象索引、依赖和非法几何保真，不写出
业务 GIS。城市级百万对象峰值内存、持久化 mmap 分片和冷/热启动性能仍无真实证据，必须
在 T028 性能门验证；T019 的物化拓扑、几何语义和一次性写出义务也未被本阶段替代。

## 下一执行门

允许进入 T009–T012：实现物理独立 Step1 DriveZone-only view、Step2
RCSDIntersection view、surface heads 与虚拟面三态约束 ledger。仍禁止训练；T013–T020
的 encoder、结构 decoder、materializer 与安全 ledger 未完成前，不得启动正式 canary。

## 当前不代表

- 不代表网络 accuracy、自动覆盖或零危险门已经通过。
- 不代表可以读取冻结测试。
- 不代表可以恢复 Segment、AdvanceRight 或 Movement。
- 不代表 P05 已接入正式主链或生产。
- 不代表历史 64D/12D 特征已经被批准为新网络主表示。
- 不代表 4,288 条身份审计使用了真实新 store 证据；本轮该项是空证据输出合同门。
- 不代表当前内存 store 已通过百万级城市资源与性能门。
