# AGENTS.md 最终版修订说明（2026-04-21）

- 基线：`2026-04-21-agents-md-revised-draft.md`
- 最终版正文：`2026-04-21-agents-md-final.md`（可直接替换仓库根目录 `AGENTS.md`）
- 本轮性质：定点修订，不重写结构

---

## 1. 本轮补入的新约束（3 类）

### 1.1 SpecKit 作为正式大型任务的默认模式

- 写入位置：**§6.2 SpecKit 模式（正式大型任务的默认模式）**
- 关键点：
  - GPT 向 CodeX 下发"正式大型任务书"时，默认走 SpecKit。
  - "正式大型任务"显式列举 4 类（需求新增 / 跨模块重构 / 影响正式业务口径 / 需要明确 spec/plan/tasks）。
  - 小中型任务**不强行**走 SpecKit。
  - SpecKit 主流程固定为 `specify / plan / tasks / implement`。

### 1.2 SpecKit 模式下的 5 类职责覆盖（多 Agent 分工约束）

- 写入位置：**§6.3 SpecKit 模式下的多职责覆盖**
- 关键点：
  - 仅适用于 §6.2 定义的正式大型任务。
  - 任务书必须覆盖 5 类职责视角：产品 / 架构 / 研发 / 测试 / QA。
  - 是任务书组织视角，不要求 5 个物理线程；可主-子 Agent、也可显式多 Agent、也可单 Agent 但任务书章节按职责划分。
  - **测试与 QA 视角不允许缺失**，缺失即视为任务书未就绪，不得进入 implement。

### 1.3 default-imp 与 SpecKit implement 阶段的共用关系

- 写入位置：**§6.4 default-imp 与 SpecKit implement 阶段的共用关系**
- 关键点：
  - 明确 `default-imp` 不是 SpecKit 替代品，SpecKit 也不取消 default-imp。
  - SpecKit 模式下，`default-imp` 作用域被限定为 implement 阶段的具体编码执行层。
  - implement 阶段默认遵循 default-imp 的 7 条关键约束（已逐条列出）。
  - 显式封堵两种误读：
    - "走了 SpecKit 就不再需要 default-imp"；
    - "default-imp 可替代 SpecKit"。

---

## 2. 章节落点对照表

| 新增约束 | 章节 | 文件位置 |
|---|---|---|
| SpecKit 默认模式与适用范围 | §6.2 | `2026-04-21-agents-md-final.md` |
| SpecKit 5 类职责覆盖 | §6.3 | 同上 |
| default-imp 与 SpecKit implement 共用关系 | §6.4 | 同上 |
| 默认编程流程（default-imp） | §6.1 | 同上 |
| 完成回报最小集（保留并独立） | §6.5 | 同上 |

§6 整体被重组为 5 个子节（§6.1-§6.5），其它章节保持不变。

---

## 3. 收窄的停机条款

### 3.1 §1.3：新增执行入口脚本

- **修订前**：草稿 §1.3 写"新增执行入口脚本（`Makefile` 目标、`scripts/`、`tools/`、模块内 `__main__.py` 等）"——会把任何 `scripts/` 下的临时脚本都纳入停机。
- **修订后**：
  - 仅针对**长期保留的正式入口**：`Makefile` 常驻目标、`scripts/` 与 `tools/` 下常驻命令、模块内 `__main__.py` / `run.py`、CLI 子命令，以及任何应登记到 `entrypoint-registry.md` 的入口。
  - 显式排除：一次性实验脚本、本地临时调试脚本、局部分析脚本（这类仍受 §4 范围边界约束，但不触发 §1.3 停机）。

### 3.2 §1.7：entrypoint-registry 与实际不一致

- **修订前**：草稿 §1.7 是"`entrypoint-registry.md` 与代码事实不一致"——任何普通任务一旦发现不一致即停机，等于把 registry 漂移负担推给所有任务。
- **修订后**：
  - 触发条件改为"本轮属于**涉及入口变更的任务**（新增 / 删除 / 重命名 / 改变官方调用方式的入口）"，且发现 registry 与事实不一致时才停机。
  - 显式说明："常规非入口任务无需主动核对 registry，不在本条触发范围内"。

两条收窄都保留了规则方向（入口治理 + registry 一致性），但把适用面从"所有任务"压缩到"真正涉及入口的任务"。

---

## 4. 最终版仍建议人工重点复核的 3 个点

1. **§6.3 的 QA 与 Testing 区分边界**
   当前把"测试（Testing）"与"QA（Quality Assurance）"并列为两个独立职责视角。需要人工确认：在你与 GPT 的实际协作里，这二者是否已有清晰的职责边界（例如 Testing = 测试用例与测试代码本身，QA = 验收口径、覆盖度、回归策略与发布闸门），否则 CodeX 在生成任务书时容易把两者混为一谈，反而触发"职责缺失"的硬限制。

2. **§1.3 的"长期保留 vs 一次性"判定标准**
   修订后引入了"长期保留的正式入口"与"一次性实验/调试脚本"的二分。该判定**没有**在 `AGENTS.md` 中给出可机械对照的形式化标准（目前依赖"是否应登记到 `entrypoint-registry.md`"作为隐含锚点）。建议确认：是否需要在 `code-boundaries-and-entrypoints.md` 中补一条"判定矩阵"，避免 Agent 在边缘情况下自我宽松解释，把"应登记的入口"当成"一次性脚本"而绕过 §1.3。

3. **§6.4 的"implement 阶段 default-imp 默认遵循"在多 Agent 场景下的传导**
   当 SpecKit 任务书按 §6.3 拆分为多职责（甚至多子 Agent）执行时，§6.4 的"implement 阶段默认遵循 default-imp"是否对所有承担 implement 工作的子 Agent 都自动生效，还是需要在 SpecKit 任务书的 `implement` 章节里显式声明一次。建议确认：是否在 `default-imp/SKILL.md` 或 SpecKit 任务书模板里加一句"任何子 Agent 进入 implement 阶段，进入即默认遵循"，避免子 Agent 因为没看到 `AGENTS.md` 而漂移。

---

## 5. 未改动的方向

按本轮约束保持不变：

- `AGENTS.md` 仍是仓库级硬规则面（不重新膨胀为方法论手册）。
- `default-imp` 守则不在 `AGENTS.md` 中重复整套（只在 §6.4 列出 implement 阶段必须遵循的关键条目）。
- 文件体量治理（§3）的前置自检 / 停机 / 登记闭环不变。
- 主阅读入口单源化（§2）不变。
- "已修改 / 已验证 / 待确认"作为强制回报项（§6.5）不变。
- §2、§4、§5、§7、§8 与上一版草稿一致，未做语义修改。
