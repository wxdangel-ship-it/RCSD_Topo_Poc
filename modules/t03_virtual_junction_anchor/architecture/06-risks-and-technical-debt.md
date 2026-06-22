# 06 Risks And Technical Debt

## 1. 文档与契约分层风险

T03 仍保留较多历史实现阶段和兼容文件名。`Association / Finalization`、`association_*`、`step7_*` 等名称会继续出现在代码、输出和审计材料中，但正式需求主结构已经切换为 `Step1~Step7`。

当前风险是读者容易把历史实现阶段误解为业务需求阶段。后续维护时应保持以下边界：

- `SPEC.md` 描述业务需求。
- `architecture/01~06` 描述模块架构设计。
- `INTERFACE_CONTRACT.md` 描述稳定入口、输入输出、状态机和验收契约。
- 历史命名与实现构件映射只在 `architecture/03-solution-strategy.md` 中保留最小说明，不再另设更深层 internal 目录。

## 2. 历史命名兼容债

现有输出文件名仍需兼容 `association_*`、`step7_*`。短期内不建议重命名，因为外部脚本、Case 包和历史审计材料仍依赖这些名称。

后续若要清理命名债，应先完成入口和产物注册审计，再以兼容别名或迁移窗口方式推进，不能直接删除旧名称。

## 3. Step3 冻结语义风险

T03 后续步骤依赖冻结 Step3 allowed space。若后续为了提高单个 Case 成功率而在 Step4-Step7 回写或放宽 Step3，会破坏“合法空间先冻结、后续只消费”的业务边界。

因此 Step3 规则调整必须作为独立业务变更处理，不能在几何 cleanup 或 closeout 中静默引入。

## 4. RCSD 数据质量风险

T03 需要在 RCSDRoad、RCSDNode、`mainnodeid`、`formway` 与空间连通关系之间建立可解释的关联。RCSD 字段缺失、方向不可信、短分段、degree-2 connector 或远端语义路口打包不完整，都可能导致 relation evidence 降级。

当前策略是把不确定性保留在 audit 与 review 层，不把局部样本反推成长期强规则。

## 5. full-input 运行风险

internal full-input 依赖 shared handle preload、per-case local context query、terminal record、progress/performance 文件和 atomic write。运行风险主要来自大批量 IO、局部上下文查询性能、early failure 后证据是否完整，以及 watch 是否误把 review 状态当 formal 状态。

后续优化应优先保持 terminal record authoritative，再调整观测和性能文件刷新策略。

## 6. 入口治理风险

repo 级主脚本 `scripts/t03_run_internal_full_input_8workers.sh` / `scripts/t03_watch_internal_full_input.sh` 只承接 full-input 运行与监控外壳，不提升为新的 repo 官方 CLI。

若未来新增、删除、重命名或改变 T03 官方调用方式，需要同步更新入口登记、模块契约和项目级入口治理文档。
