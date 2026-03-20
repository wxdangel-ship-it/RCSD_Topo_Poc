# T01 数据预处理 Skill v1.0.0 规格

## 1. 文档状态
- 状态：`Accepted baseline / runtime optimization in progress`
- 当前阶段：`Step2 large-scale bottleneck remediation and runtime observability`
- 本文用途：
  - 固化当前已确认的 T01 accepted baseline 业务语义
  - 说明官方 Step1-Step5 口径与当前实现映射
  - 约束运行期优化不得回退 freeze baseline

## 2. 当前 accepted architecture

### 2.1 官方 Step1-Step5 口径
1. Step1：候选 Pair 发现
2. Step2：首轮 `validated / trunk / segment_body` 构建
3. Step3：语义修正与 refreshed Node / Road 更新
4. Step4：基于 residual graph 的下一轮构段
5. Step5：分阶段 residual graph 收尾（Step5A / Step5B / Step5C）并统一刷新

### 2.2 当前实现映射
- Step1：`t01-step1-pair-poc`
- Step2：`t01-step2-segment-poc`
- Step3：`t01-s2-refresh-node-road`
- Step4：`t01-step4-residual-graph`
- Step5：`t01-step5-staged-residual-graph`
- 官方端到端入口：`t01-run-skill-v1`

### 2.3 当前 accepted 范围
- 首轮：Step1 / Step2 / Step3
- 后续轮次：Step4 / Step5A / Step5B / Step5C
- 当前不纳入 Skill v1.0.0 的内容：
  - Step6
  - 单向 Segment
  - Step3 完整语义归并
  - 完整多轮闭环治理

## 3. Step1 / Step2 accepted 语义

### 3.1 Step1
- Step1 只输出 `pair_candidates`
- Step1 不代表最终有效 pair
- 最终有效性由后续构段 / 验证阶段判定

### 3.2 Step2
- Step2 输出：
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- `final segment` 不再表达 all related roads
- `segment_body` 只表达当前 validated pair 的 pair-specific road body
- 弱规则不在 Step2 中硬删，统一进入 `step3_residual`

### 3.3 Step2 强规则
- A：`non-trunk component` 触达其他 terminate（非 A / B）时，不进入 `segment_body`
- B：`non-trunk component` 吃到其他 validated pair trunk 时，不进入 `segment_body`
- C：过渡路口出现“同向进入 + 同向退出”时，该方向停止追溯
- mirrored bidirectional case 已纳入规则 C

### 3.4 已闭环问题
- 右转专用道误纳入问题已解决
- `node = 791711` 的 T 型双向退出误追溯问题已解决

## 4. trunk / 最小闭环 accepted 语义

### 4.1 双向 road 语义
- `direction = 0 / 1` 的双向 road，业务上视为两条方向相反的可通行 road
- 因此一条双向直连 road 的正反镜像通行，本身可以构成合法最小闭环

### 4.2 split-merge 混合通道
- 合法 Segment 不要求物理上始终是两条完全分离的 road
- 当前 accepted 语义允许：
  - 先分后合
  - 合后再分
  - 分合混合
  - 共享双向 road 的混合通道
- 只要整体仍满足合法的 `A -> B` 与 `B -> A` 通道，即可成立 trunk

### 4.3 semantic-node-group closure
- trunk 以语义路口为单元，而不是只看纯几何首尾闭环
- 若正反路径在 semantic-node-group 层面的有向图已经闭合，则即使物理几何不开环，也可成立 trunk
- 该口径同时支持：
  - `mainnode group`
  - `mainnodeid = NULL` 的单点路口

## 5. 层级边界 / 历史高等级边界
- 更低等级构段必须在更高等级历史路口中断
- 当前轮 `terminate / hard-stop` 必须包含历史高等级边界 `mainnode`
- 历史边界同时作用于：
  - pair 搜索阶段
  - segment 收敛阶段
- 对当前轮而言，历史高等级边界 `mainnode` 同时具有：
  - `seed`
  - `terminate`
  - `hard-stop`
- 搜索命中历史边界时，应记录为 terminal candidate，然后停止继续穿越

## 6. `mainnodeid = NULL` 单点路口语义
- 若 `mainnodeid` 为空，则该 node 自身视为一个独立语义路口
- 该 node 自身就是该语义路口的 mainnode
- `mainnodeid = NULL` 不等于“不是路口”
- 只要满足当前轮输入规则，就应正常进入 `seed / terminate`
- 当前轮合法 `seed / terminate` 节点，不得再被当前轮 `through_node` 吞掉

## 7. residual graph 多轮语义
- 后续轮次使用 refreshed `Node / Road` 作为输入基础
- 节点筛选使用刷新后的 `grade_2 / kind_2 / closed_con`
- 已有非空 `segmentid` 的 road 在后续轮次工作图中剔除，视为不存在
- residual graph 已成为正式的多轮构段工作方式

## 8. Step4 / Step5 accepted 输入与提取约束

### 8.1 Step4
- 输入节点：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,2048}`
  - `closed_con in {1,2}`
- 工作图：
  - 剔除已有非空 `segmentid` 的 road
- `seed / terminate`：
  - 当前轮命中节点
  - `S2` 历史边界端点
- Step4 新构成 road：
  - `s_grade = "0-1双"`
  - `segmentid = "A_B"`

### 8.2 Step5A
- 输入节点：
  - `closed_con in {1,2}`
  - 且满足：
    - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 = 4` 且 `grade_2 = 3`
- 工作图：
  - 使用 Step4 refreshed road，并剔除已有 `segmentid` 的 road
- `seed / terminate` 并入：
  - `S2 + Step4` 历史边界端点

### 8.3 Step5B
- 在 Step5A residual graph 上运行
- 输入节点：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`
- 只剔除 Step5A 新 `segment_body` road
- 不刷新属性
- `S2 + Step4` 历史边界端点并入 `seed / terminate`
- Step5A 新端点只用于 `hard-stop`

### 8.4 Step5C
- 在 Step5B residual graph 上运行
- 输入节点：
  - `closed_con in {1,2}`
  - `kind_2 in {1,4,2048}`
  - `grade_2 in {1,2,3}`
- 只剔除 Step5B 新 `segment_body` road
- 不刷新属性
- `S2 + Step4` 历史边界端点并入 `seed / terminate`
- Step5A / Step5B 新端点只用于 `hard-stop`

### 8.5 Step5 统一刷新
- Step5A / Step5B / Step5C 完成后，统一刷新：
  - `grade_2`
  - `kind_2`
  - `s_grade`
  - `segmentid`
- Step5 新构成 road：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`

## 9. Node / Road 刷新语义

### 9.1 Node
- `grade_2 / kind_2` 是持续滚动的当前语义字段
- 原始 `grade / kind` 不覆盖
- 刷新按 `mainnode` 执行，subnode 保持当前值
- 优先级：
  1. 当前轮 validated pair 端点：保持当前值
  2. 所有 road 都在一个 segment：`grade_2=-1, kind_2=1`
  3. 唯一 segment + 其余全右转专用道：`grade_2=3, kind_2=1`
  4. 唯一 segment + 其余非 segment road 构成多进多出：`grade_2=3, kind_2=2048`
  5. 其他情况：保持当前值

### 9.2 Road
- `segmentid` 表示 road 已属于某个 validated pair 的 `segment_body`
- 已有非空 `segmentid / s_grade` 的 road，后续轮次保持原值不覆盖
- `s_grade` 当前口径：
  - Step2：`0-0双`
  - Step4：`0-1双`
  - Step5A / Step5B / Step5C：`0-2双`

## 10. XXXS freeze baseline 约束
- `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/` 是当前 Skill v1.0.0 的轻量 freeze 审计包
- 外网完整 freeze run 保留在 `outputs/_freeze/`
- 后续任何优化若与该 freeze baseline 不一致，默认视为回退或显式变更
- 未经用户明确确认，不得更新该 freeze baseline

## 11. 官方 runner 的运行期契约
- 官方入口：`t01-run-skill-v1`
- 默认 `debug=true`
  - 保留中间结果
  - 服务大规模验证前的 case 审计与视觉排查
- 显式 `--no-debug`
  - 只改变中间产物与持久化 I/O
  - 不改变最终业务结果

### 11.1 当前已纳入的执行层优化
- Step1 / Step2 / refresh / Step4 / Step5 输入读取固定 `2` worker 并行
- runner 在阶段结束后执行 `gc.collect()`
- runner 对各阶段做 `tracemalloc` 峰值记录
- `debug=false` 时使用临时 stage 目录，减少最终目录中的无意义中间文件

### 11.2 当前已纳入的运行期可观测性
- 命令行进度：
  - `RUN START`
  - `[n/N] START stage`
  - `[n/N] DONE stage`
  - `[n/N] FAIL stage`
- 结构化产物：
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`

### 11.3 当前未完成能力
- 当前仍不是完整全内存流水线
- 当前仍未引入核心 pair / trunk / validated 决策层并发
- 当前仍需补齐 Step2 内部子阶段进度
- 当前仍需补齐 Step2 第一版 low-memory 策略

## 12. 当前推荐基线
- 当前唯一主方案：`t01-run-skill-v1`
- 当前推荐输入基线：
  - 原始 `Node / Road`
  - 或最新一轮 refreshed `nodes.geojson / roads.geojson`
- 当前推荐输出基线：
  - Step5 refreshed `nodes.geojson / roads.geojson`
  - Skill v1.0.0 官方 `nodes.geojson / roads.geojson`
  - 对应 freeze compare PASS 报告
