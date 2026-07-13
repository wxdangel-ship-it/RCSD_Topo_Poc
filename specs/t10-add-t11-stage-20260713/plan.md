# T10 工作流增加 T11 阶段计划

## 实现

1. 新增内部 `case_runner_t11.py` adapter，负责 T11 输入门禁、正式入口调用、run root 与必要输出审计。
2. 将 `t11` 插入 `T10_E2E_STAGE_ORDER`、module mapping、dispatcher 和 facade 导出。
3. 在 innernet full pipeline 中插入 T11 调用，扩展 stage normalize/order/resume、manifest 与 final summary。
4. 为 innernet full root 增加 T11 显式输入路径发现，避免递归同名文件误选。
5. 同步 T10/T11 源事实、架构、接口契约、入口登记与体量审计。

## 验证

1. 新增 adapter、stage order、stop-after 和 shell contract 单元测试。
2. 运行 T10/T11 定向测试及 shell `bash -n`。
3. 使用 `1885118` 先验证 T11 插入后的 Case manifest 与产物。
4. 完成六用例工作流回归，核对每例 `t06_step3 < t11 < t09_step12`、T11 产物和总体状态。
5. 执行 60KiB 扫描、`git diff --check` 与临时分支提交。

## 风险

- `case_runner_pipeline.py` 已接近 60KiB：T11 实现放入独立内部模块，仅在 dispatcher 增加最小分支。
- full pipeline legacy run 无 T11：新完成口径要求先补跑 T11，文档明确迁移方式。
- full pipeline 同名文件较多：T11 input discovery 增加当前固定目录相对路径，保留原 Case layout 兼容路径。
- T11 生成 timestamp run root：runner 从 stdout JSON/唯一 `run_*` 目录审计实际 root，不猜测固定名称。
