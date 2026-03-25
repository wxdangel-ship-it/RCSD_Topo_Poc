# 04 方案策略

## 状态

- 当前状态：`模块级方案策略说明`
- 来源依据：
  - 官方 CLI 子命令
  - stage1 实现
  - 当前单元测试与 smoke

## 主策略

1. 通过统一 CLI 入口读取 `segment / nodes / DriveZone / RCSDIntersection`
2. 对输入字段、CRS 与 geometry 做显式校验，不做隐式猜测
3. 从 `pair_nodes + junc_nodes` 提取单 `segment` 的目标 junction 集合并去重
4. 按 `mainnodeid` 分组 / 单点兜底组装 junction group
5. 在 `EPSG:3857` 下对 junction group 与 `DriveZone` 做 stage1 gate
6. 对 `has_evd = yes` 的组，用 `RCSDIntersection` 做 stage2 anchor recognition / anchor existence
7. 对 stage2 后仍未锚定、但有资料的路口，进入 stage3 `virtual intersection anchoring`
8. stage3 统一复用单 case worker，支持：
   - `case-package` baseline regression
   - `full-input` 指定 `mainnodeid`
   - `full-input` 自动识别候选并批量处理
9. stage3 构造局部 patch、分支证据、RC 关联与虚拟路口面，并汇总单 case 与批次级输出
10. 产出 `nodes.has_evd`、`nodes.is_anchor`、`segment.has_evd`、`summary`、`audit / log` 与 stage3 产物

## 阶段串联策略

1. stage1 负责回答“该路口是否有道路面资料”。
2. stage2 负责回答“该路口是否已经稳定锚定到 `RCSDIntersection`”。
3. stage3 负责回答“对于有资料但未锚定的路口，是否能构造合理的虚拟路口面，并将其锚定到 own-group nodes / RCSDNode / RCSDRoad 局部组件”。
4. 文本证据包不构成新的业务阶段；它位于 stage3 之后，只承担单 case 复核、外部复现与回传支撑职责。

## 降级与失败策略

- 业务级 `no`：
  - `junction_nodes_not_found`
  - `representative_node_missing`
  - `no_target_junctions`
- 执行级失败：
  - `missing_required_field`
  - `invalid_crs_or_unprojectable`
- POC 级明确失败或风险：
  - `anchor_support_conflict`
  - `no_valid_rc_connection`
  - `node_component_conflict`
- 设计原则：
  - 不能 silent skip
  - 不能把执行失败伪装成业务 `no`
  - 不能为环岛与代表 node 缺失补充新的泛化 fallback
  - 不能为了通过单 case 把错误 RC 分支或错误节点硬凑进 polygon

## Stage3 虚拟路口锚定策略

1. stage3 先检查代表 node 的 `has_evd / is_anchor / kind_2` 是否落在当前 baseline 范围内。
2. 从代表 node 周边构造局部 patch，并在统一 CRS 下加载 `nodes / roads / DriveZone / RCSDRoad / RCSDNode`。
3. 先做保守的 RC association，再单独构造 `polygon-support`，两者允许解耦。
4. `polygon-support` 必须覆盖 own-group nodes，并只允许吸纳与当前路口局部组件一致的紧凑 RC 支撑子图。
5. 若 RC 不存在与 roads 同方向的有效局部分支，不得拿其它横向或直行 RC 替代。
6. 最终 polygon 必须通过 support validation；无法同时满足 own-group nodes 与局部 RC 支撑时，明确失败而不是 silent fix。
7. `case-package` 模式作为 baseline regression 与小样本复核入口保留，不允许回退。
8. `full-input` 模式作为正式 baseline 入口，统一承接单点验证与自动识别候选两类业务诉求，并支持 `max_cases / workers`。
9. `review_mode` 只放宽 anchor gate 与 RC outside DriveZone 的处理方式，用于人工复核，不改变正式契约边界。

## 文档策略

- 稳定阶段链与边界由 `architecture/*` 承担。
- 输入、输出、入口、参数类别与验收由 `INTERFACE_CONTRACT.md` 承担。
- `README.md` 只给操作者入口与常见运行方式。
