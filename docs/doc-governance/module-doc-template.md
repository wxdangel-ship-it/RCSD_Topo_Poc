# 模块文档模板与写法规则

## 1. 模板来源

当前模块文档模板以 `modules/t03_virtual_junction_anchor` 的整改结果为参考。T03 已验证的结构特点是：

- 高层 `README.md` 只做阅读入口和索引，不承载大段需求。
- `SPEC.md` 承载模块需求，用业务语言解释“为什么存在、解决什么问题、什么算对”。
- `INTERFACE_CONTRACT.md` 瘦身为接口契约速查，不再承载详细业务策略。
- `architecture/01~06` 与项目级架构目录同构，但允许模块按实际需要缺失部分文件。
- `architecture/03-solution-strategy.md` 是需求具体实现策略，按业务步骤解释如何落地。
- 若模块确有已确认 baseline 或兼容补充材料，可放在 `architecture/` 下的非编号文件中，但必须在 `README.md` 中说明它是补充材料，不占用 01-06 主结构。
- `history/` 只保留历史 closeout 和背景，不替代当前文档。

## 2. 标准文件职责

| 文件 | 应承载 | 不应承载 |
|---|---|---|
| `README.md` | 当前状态、文档职责、入口类别、阅读顺序 | 详细业务规则、字段表、运行教程 |
| `SPEC.md` | 模块定位、业务目标、范围、上下游、输入输出、关键业务步骤、核心场景概念、对错边界 | 伪代码、大段参数、实现文件清单 |
| `INTERFACE_CONTRACT.md` | 稳定输入、输出、状态、入口、最小审计字段和值域 | 业务背景长文、完整算法策略、历史 closeout |
| `architecture/01-introduction-and-goals.md` | 架构上下文、目标、范围、兼容边界、非目标 | 入口参数表、模块历史流水账 |
| `architecture/02-data-and-domain-model.md` | 输入对象、业务对象、领域分层、字段 / CRS / 数据形态、下游语义 | 重复 `INTERFACE_CONTRACT.md` 的完整契约 |
| `architecture/03-solution-strategy.md` | 每个业务步骤的业务目的、原则、落地策略、输出审计、对错边界 | 只列代码文件、只列参数、只贴伪代码 |
| `architecture/04-evidence-and-audit.md` | formal、review-only、internal、handoff 证据和审计分层 | 运行日志全文、临时输出目录说明 |
| `architecture/05-quality-requirements.md` | 业务正确性、输出稳定性、review/formal 分层、观测性能、治理要求 | 与代码无关的泛化质量口号 |
| `architecture/06-risks-and-technical-debt.md` | 历史命名债、数据质量风险、入口治理风险、跨模块 handoff 风险 | 当前需求正文的替代版本 |
| `history/` | 历史阶段材料和 closeout | 当前需求、当前接口契约 |

## 3. 业务表达规则

1. 先说明业务问题，再说明实现方式。
2. 每个关键状态字段都要说明它回答的业务问题，不能只列值域。
3. 每个关键概念都要说明它与上下游的关系。例如 T03 的 `association_class` 只说明 RCSD 证据角色，不能替代 `step7_state` 或 relation evidence。
4. 参数和字段必须服务业务说明；如果必须写参数，应说明这个参数保护什么业务边界。
5. 对错边界要写成业务判断，例如“surface accepted 不等于 relation 成功”，而不是只写“字段 A 不等于字段 B”。
6. 历史实现命名要标出兼容边界，避免读者把旧阶段名理解成当前需求主结构。

## 4. 模块整改使用方式

整改模块文档时，优先读取代码、测试和实际入口来确认事实：

1. `src/rcsd_topo_poc/modules/<module>/`
2. `src/rcsd_topo_poc/cli.py`
3. `scripts/` 中已登记或实际使用的模块脚本
4. `tests/` 中对应模块测试
5. `docs/repository-metadata/entrypoint-registry.md`

现有模块文档只能作为待核对材料，不作为最终事实来源。
