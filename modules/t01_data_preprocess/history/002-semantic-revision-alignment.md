# 002 - 业务语义修正对齐说明

## 1. 背景
- 本文档记录 T01 在问题修复过程中形成、并最终被 accepted baseline 吸收的业务语义修正
- 目的不是解释代码细节，而是让业务讨论、GPT 复盘与当前代码实现保持一致

## 2. 输入约束修正

### 问题
- 早期理解中，后续轮次的输入规则、历史边界与当前轮合法端点之间的关系不够清晰
- 导致出现：
  - 当前轮合法端点被当作 `through_node`
  - `mainnodeid = NULL` 的单点路口被误当成“不是路口”
  - 低等级轮次越过高等级已确认路口继续构段

### 修正前理解
- 当前轮输入节点只是一组“可用候选”
- 命中输入规则的节点仍可能被压缩成 through
- 历史边界主要被理解成搜索停止条件

### 修正后理解
- 命中当前轮输入规则的节点就是当前轮合法 `seed / terminate`
- 当前轮合法 `seed / terminate` 不得再被当前轮 `through_node` 吞掉
- `mainnodeid = NULL` 的单点路口也是合法语义路口
- 历史高等级边界 mainnode 同时具备：
  - `seed`
  - `terminate`
  - `hard-stop`

### 当前 accepted 口径
- Step4 / Step5 的输入以 refreshed `grade_2 / kind_2 / closed_con` 为准
- `mainnodeid = NULL` 的 node 自身即语义路口 ID
- 当前轮合法端点必须真正作为端点参与搜索

## 3. Step2 segment 语义修正

### 问题
- 早期 Step2 的最终 segment 过宽
- 右转专用道、T 型外伸、通往其他 terminate 的分支会被错误吸入

### 修正前理解
- `segment` 接近“当前 pair 周边相关道路集合”
- 弱规则和强规则混杂

### 修正后理解
- Step2 `segment_body` 只表达当前 validated pair 的 pair-specific road body
- 强规则命中的 component 必须移出 `segment_body`
- 弱规则不做 Step2 硬裁剪，只进入 `step3_residual`

### 当前 accepted 口径
- Step2 输出：
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- 右转专用道误纳入与 `791711` T 型双向退出误追溯问题已经闭环

## 4. 层级边界 / 历史高等级边界修正

### 问题
- 低等级轮次出现跨越高等级已确认路口继续构段的错误
- 典型表现是 pair 搜索或 segment 收敛穿越本应中断的高等级边界

### 修正前理解
- 历史边界更多被当作“只阻断搜索”的辅助条件
- 没有同时作用于 pair 搜索与 segment 收敛

### 修正后理解
- 更低等级构段必须在更高等级历史路口中断
- 历史高等级边界 mainnode 必须同时作用于：
  - pair 搜索阶段
  - segment 收敛阶段
- 命中历史边界时，应：
  - 记为 terminal candidate
  - 然后停止继续穿越

### 当前 accepted 口径
- 历史高等级边界 mainnode 是当前轮的：
  - `seed`
  - `terminate`
  - `hard-stop`
- 不允许再出现“只阻断、不成对”的黑箱 stop

## 5. residual graph 多轮构段语义修正

### 问题
- 单轮 Step1 / Step2 / Step3 与后续多轮 residual graph 逻辑曾经混杂
- 后续轮次的输入、工作图与刷新时机不够稳定

### 修正前理解
- 后续轮次更像“继续试验”，不是正式工作方式

### 修正后理解
- residual graph 已成为多轮构段的正式工作方式
- 后续轮次统一使用 refreshed `Node / Road`
- 已有非空 `segmentid` 的 road 在后续工作图中剔除，视为不存在

### 当前 accepted 口径
- 首轮：
  - Step1 / Step2
- 后续：
  - Step4
  - Step5A / Step5B / Step5C
- Step5A / Step5B / Step5C 之间只剔除更早阶段新 `segment_body` road，不刷新属性
- Step5 三阶段完成后统一刷新

## 6. mainnode = NULL 单点路口语义修正

### 问题
- 早期实现里，`mainnodeid = NULL` 的点容易被误认为“不是路口”或被 through 吞掉

### 修正前理解
- 单点路口在没有 mainnode group 时，语义地位不稳定

### 修正后理解
- 若 `mainnodeid = NULL`，该 node 自身就是独立语义路口
- 只要命中当前轮输入规则，就应进入 `seed / terminate`
- 不得再在同一轮被当作 through

### 当前 accepted 口径
- `mainnodeid = NULL` 不等于“不是路口”
- trunk 与 segment 语义同样支持单 node 路口

## 7. trunk 语义修正

### 问题
- 早期 trunk 判定过度依赖纯几何闭环
- 对双向 road、split-merge、语义路口闭合支持不完整

### 修正前理解
- 只有几何上严格闭合的回环更容易被接受

### 修正后理解
- 双向 road 视为两条方向相反的可通行 road
- 一条双向直连 road 的正反镜像通行可以直接构成最小闭环
- 合法 Segment 中允许先分后合、合后再分、共享双向 road 的分合混合结构
- trunk 闭环以语义路口为单元，semantic-node-group closure 也可成立

### 当前 accepted 口径
- trunk 的判断优先以有向通道语义与语义路口闭环为准
- 不再把“纯几何不开环”当作唯一拒绝条件

## 8. 当前 accepted baseline
- Step1 只输出 `pair_candidates`
- Step2 首轮完成 `validated / rejected + trunk + segment_body + step3_residual`
- Step4 / Step5 在 residual graph 上继续推进
- 推荐输入基线：
  - 最新一轮 refreshed `nodes.geojson / roads.geojson`
- 推荐输出基线：
  - Step5 refreshed `nodes.geojson / roads.geojson`

## 9. 尚未纳入正式模块完整构建的内容
- Step6
- 单向 Segment
- Step3 完整语义归并
- 完整多轮闭环治理
- 正式统一编排入口
- 更完整的回归 / 验收体系
