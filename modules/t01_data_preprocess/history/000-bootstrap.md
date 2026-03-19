# T01 初始框架建立记录

## 1. 已确认事实：建立背景

- 本轮任务目标是为 T01 建立初始模块文档框架与规格占位框架。
- 当前重点是把已经明确的模块定位、输入事实和待确认问题落仓。
- 当前阶段仍处于需求澄清期，不进入实现设计和编码阶段。
- 当前落仓仅表示建立文档草案位，不等于项目级生命周期已将 T01 升级为正式业务模块。

## 2. 已确认事实：当前已确认信息来源

- 用户本轮任务书中给出的 T01 模块定位与输入字段说明。
- repo root `AGENTS.md`
- repo root `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/doc-governance/README.md`
- `docs/doc-governance/module-lifecycle.md`
- `docs/repository-metadata/README.md`
- `docs/repository-metadata/repository-structure-metadata.md`
- `modules/_template/AGENTS.md`
- `modules/_template/INTERFACE_CONTRACT.md`
- `modules/_template/README.md`

## 3. 当前理解/归纳：本轮落仓范围

- 建立 `specs/t01-data-preprocess/` 下的 `spec.md`、`plan.md`、`tasks.md`。
- 建立 `modules/t01_data_preprocess/` 下的 `AGENTS.md`、`INTERFACE_CONTRACT.md`、`README.md`。
- 建立 `modules/t01_data_preprocess/architecture/overview.md`。
- 建立 `modules/t01_data_preprocess/history/000-bootstrap.md`。
- 本轮不创建任何实现代码、测试、脚本或运行产物。

## 4. 待确认决策点：明确未解决问题

- 路段提取边界定义。
- 路口类型重赋值对象与规则。
- 低可信字段的启用条件。
- 输出契约与失败契约。
- 下游消费关系。

## 5. 已确认事实：本轮补充确认口径

- `mainnodeid` 是当前语义路口聚合主依据。
- 当 `mainnodeid` 为空值、缺失、`0`、空字符串时，认为当前 Node 自身就是语义路口，并以 `id` 为主。
- `direction` 中 `0` 与 `1` 当前都视为双方向。
- 输入 CRS 统一归一化至 `3857`，字段统一做归一化处理。
- 缺失 `Node.id` 引用及其它输入问题，当前口径为报异常，但不中断其它处理。

## 6. 当前不纳入范围：下一轮讨论主题

- 输出成果与最小属性集。
- 失败与审计口径。
- 路段提取规则细化。
- 路口类型重赋值规则细化。
- 上下游接口假设确认。
