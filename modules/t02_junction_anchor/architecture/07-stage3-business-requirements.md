# 07 Stage3 业务需求说明

## 1. 文档定位

- 状态：`current implementation aligned business requirements`
- 作用：
  - 将 stage3 `virtual intersection anchoring` 当前需要满足的业务要求单独整理出来。
  - 明确“为什么要生成虚拟路口面”“什么结果算业务成功”“什么情况即使出面也不能算成功”。
  - 本文档不替代 accepted baseline；业务边界仍以 [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/architecture/06-accepted-baseline.md) 与 [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md) 为准。
- 当前实现依据：
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py)
  - [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)
  - 当前 stage3 样例回归与 smoke

## 2. Stage3 要解决的业务问题

stage3 要回答的不是“程序能不能跑完”，而是：

1. 对于 `has_evd = yes` 但未稳定锚定的路口，能否构造一个符合路口口门认知的虚拟路口面。
2. 这个面是否能同时覆盖 own-group nodes，并与局部 `RCSDRoad / RCSDNode` 证据保持一致。
3. 当 RC 证据缺失、歧义、冲突时，应该记为：
   - 可接受成功
   - 待复核
   - 明确失败

因此，stage3 的核心业务对象不是“任意 polygon”，而是：

- 一个围绕目标 `mainnodeid` 的、可解释的局部路口面
- 一组与该面相匹配的局部 RC 关联
- 一套能区分“资料缺失型”和“资料矛盾型”的验收口径

## 3. 业务输入前提

### 3.1 候选前提

当前 stage3 正式候选口径是：

- `has_evd = yes`
- `kind_2 in {4, 2048}`
- 非 `review_mode` 下默认 `is_anchor = no`

说明：

- stage3 只处理“有资料但未稳定锚定”的路口，不重算 stage1 / stage2。
- `review_mode` 只服务人工复核，不改变正式业务边界。

### 3.2 局部输入数据

stage3 当前业务上依赖五类局部输入：

- `nodes`
- `roads`
- `DriveZone`
- `RCSDRoad`
- `RCSDNode`

业务语义分工：

- `nodes / roads`：表达当前路口自身拓扑与口门方向
- `DriveZone`：约束“有资料的道路面区域”
- `RCSDRoad / RCSDNode`：提供局部 RC 连通证据，但不允许反客为主替代错误方向的 roads 口门

## 4. Stage3 业务需求

### 4.1 必须先构造“路口面”，而不是先找 RC

stage3 的第一业务要求是：

- 路口面必须首先围绕目标路口 own-group nodes 和本地道路口门成立。

这意味着：

- `RCSDRoad / RCSDNode` 是支撑证据，不是主导真值。
- 当 RC 缺失时，只要路口面本身仍成立，不应机械判失败。
- 当 RC 与目标路口矛盾时，即使画出了面，也不能算成功。

### 4.2 own-group nodes 必须被覆盖

这是 stage3 最硬的几何要求：

- 虚拟路口面必须覆盖目标 own-group nodes。

业务含义：

- polygon 不能偏到邻接路口
- polygon 不能只覆盖路口一角
- polygon 不能只靠 RC 支撑补出一个与目标主节点组脱节的面

### 4.3 路口面必须体现“非主方向口门”

对于交叉口、T 型口、并入口等场景，stage3 不能只给出一个主方向核心小块，而必须尽量体现真实的非主方向口门。

业务要求拆成两层：

- 主方向：需要体现路口核心的贯通方向
- 非主方向：需要体现支路、匝道或 T 型口门的局部展开

如果只生成主方向中心小块，而没有体现应有的非主方向口门，则：

- 这不是效果成功
- 最多只能记为待复核

### 4.4 RC 缺失不等于失败

当前业务上已经明确接受以下场景：

- 局部没有任何 RCSD 数据
- 局部有 RCSD 数据，但没有连到目标路口组件
- RC 只剩零散残段，不足以形成有效关联

这些场景只要 polygon 本身成立，就不应自动失败。

对应业务语义是：

- `RC missing` 可以接受
- `RC contradictory` 不可接受

### 4.5 RC 矛盾必须明确失败

下列属于“RC 矛盾型”，即使有 polygon 也不能直接算成功：

- RC 落在目标 patch 中，但明显超出 `DriveZone`
- RC 与目标路口主方向 / 非主方向组件冲突
- RC 指向其他邻接路口，却被错误吸纳为当前路口支撑
- polygon 覆盖了额外本地路口节点，说明面已越界到邻接路口

业务含义：

- Stage3 不能用“多吃一些 RC / 多并一些 roads”来掩盖矛盾
- 不能为了让 case 成功而静默吸纳错误组件

### 4.6 几何结果必须可接受

当前 stage3 对几何结果的业务要求至少包括：

- 应为单一主面
- 不应有空洞
- 不应有明显异常凸起
- 不应有明显异常凹陷
- 不应吞入邻接路口或对向无关道路

这不是单纯美观要求，而是：

- 几何形态直接反映路口口门是否被算法正确建模

### 4.7 成功定义必须是“效果成功”

当前 stage3 明确区分：

- `flow_success`
  - 算法流程完成并输出了产物
- `success`
  - 业务效果通过验收

业务上真正应该下游使用的是 `success`，不是 `flow_success`。

因此：

- 允许“流程成功但效果失败”
- 不允许“效果失败但仍记 success=true”

### 4.8 输出必须可审计

stage3 当前业务要求不仅是输出 polygon，还要输出：

- `status`
- `acceptance_class`
- `acceptance_reason`
- `branch_evidence`
- `associated_rcsdroad / associated_rcsdnode`
- `audit / perf / progress`
- debug render

这些输出的业务目的，是让失败 case 能够被快速分成：

- 真失败
- RC 缺口型成功
- 规则偏保守导致的待修 case

## 5. 结果分类口径

### 5.1 accepted

表示：

- 业务上认为该路口面已可接受
- `success = true`

当前 accepted 不只包含 `stable`，还包含部分“RC 缺口型但面成立”的状态子类。

### 5.2 review_required

表示：

- 程序已经跑出结果
- 但当前机器证据不足以判成正式成功

这类 case 是后续效果优化的主要来源。

### 5.3 rejected

表示：

- 存在硬失败、强冲突、或业务明确不能接受的矛盾

典型例子：

- `rc_outside_drivezone`
- `anchor_support_conflict`
- `main_direction_unstable`

## 6. 业务需求与当前状态映射

### 6.1 成功态

当前 stage3 成功态并不只是一种：

- `stable`
- `surface_only` 的可接受子类
- `no_valid_rc_connection` 的 RC 缺口型子类
- `ambiguous_rc_match` 的非矛盾紧凑 polygon 子类
- `node_component_conflict` 的局部可解释子类

这反映的业务事实是：

- “没有拿到完整 RC”不等于“路口面错”

### 6.2 失败态

当前明确失败主要分两类：

- 几何 / 支撑无法自洽
- RC 与当前路口存在实质矛盾

### 6.3 当前唯一硬守门样例

在现有本地样例集中，当前持续作为硬守门失败样例的是：

- `520394575`

它的业务意义不是“所有 `rc_outside_drivezone` 都必失败”，而是：

- 不能为了放开 RC 缺口型 case，把真正的 RC 矛盾型 case 一起放坏

## 7. 本文档不定义的内容

以下内容仍不在当前正式 stage3 业务需求内：

- 最终唯一锚定决策闭环
- 概率 / 置信度
- 候选打分体系
- 全量产线级治理闭环
- 面向未来业务的环岛新规则

## 8. 与算法文档的关系

- 本文档回答“stage3 为何这样判、业务上到底想要什么”。
- [08-stage3-algorithm-strategy.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/architecture/08-stage3-algorithm-strategy.md) 回答“当前代码如何用局部 patch、分支证据、栅格 mask 和支撑校验把这些需求落地”。
