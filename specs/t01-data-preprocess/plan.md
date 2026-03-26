# T01 计划

## 当前阶段
- `step 1 doc consistency audit on main`
- `step 2 workspace cleanup pending`
- `step 3 Step2 performance/memory audit pending`
- `step 4 Step2 optimization pending`

## 当前目标
1. 先把最新已合入的 T01 代码行为回写到正式需求基线文档。
2. 在文档提交后清理本地脏数据，恢复本地/远端一致。
3. 独立审计 Step2 的性能、内存与死机风险热点。
4. 再切分支做 Step2 优化，确保业务结果与当前人工验收基线一致。

## 实施批次

### 批次 A：正式文档一致性审计
- 审计 `overview / 06-accepted-baseline / INTERFACE_CONTRACT / README` 与当前代码的一致性。
- 明确补入：
  - `bootstrap node retyping`
  - family-based `grade_2 / kind_2` refresh retyping
  - 当前 working bootstrap 的阶段顺序
- 清除旧的泛化 `2048` 刷新叙述。

### 批次 B：spec-kit 过程文档重置
- 将当前 `spec.md / plan.md / tasks.md` 从上一轮 `GeoPackage I/O migration` 主题切换到本轮“文档审计 + Step2 性能优化”主题。
- 保留上一轮实现已完成的事实，但不再把其作为当前 spec-kit 主目标。

### 批次 C：main 收口与工作区清理
- 将文档一致性修订提交到 `main` 并推送。
- 清理本地脏数据，确保本地 `main` 与 `origin/main` 一致。

### 批次 D：Step2 性能 / 内存审计
- 识别 Step2 的高耗时路径、峰值内存热点与潜在 O(N^2)+ 组件。
- 输出内网死机风险的可解释分析。
- 形成优化点清单与优先级。

### 批次 E：Step2 优化实现
- 在独立分支上实施 Step2 优化。
- 优先优化性能 / 内存，不改变 accepted baseline 业务语义。
- 通过 `XXXS1-8` 与相关单测回归确认无业务回退。

## 依赖与风险
- 当前工作区存在与 T01 无关的脏数据，main 收口前必须避免误提交。
- T01 文档当前最大的风险不是缺文档，而是“文档仍描述旧逻辑”，容易误导后续治理。
- Step2 优化若直接改变 pair / trunk 仲裁策略，容易破坏已通过样例；性能优化必须优先聚焦结构与数据流，而非业务门控。
- 内网死机历史说明 Step2 可能同时存在 CPU 与内存双重瓶颈，审计阶段不能只看耗时。

## 回归策略
1. 文档阶段：
   - 以源码为准逐条审计正式文档
   - 只提交文档与 spec-kit 过程文档
2. 清理阶段：
   - 确认 `git status --short` 为空
   - 确认本地 `main` 与 `origin/main` 一致
3. 性能审计阶段：
   - 记录 Step2 热点函数、候选规模与中间对象体量
   - 输出风险点与优化建议
4. 优化阶段：
   - 单测先行
   - 再跑 `XXXS1-8`
   - 以人工已通过样例为非回退基线

## 文档落点
- 过程文档：
  - `spec.md`
  - `plan.md`
  - `tasks.md`
- 正式文档：
  - `modules/t01_data_preprocess/architecture/overview.md`
  - `modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
  - `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
  - `modules/t01_data_preprocess/README.md`

## 边界
- 不新增执行入口脚本。
- 不顺手推进新的业务规则扩张。
- 不自动刷新 freeze baseline。
- 文档阶段不混入 Step2 性能优化代码实现。
