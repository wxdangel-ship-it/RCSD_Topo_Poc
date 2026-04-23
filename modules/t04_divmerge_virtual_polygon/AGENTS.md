# t04_divmerge_virtual_polygon 执行约束

- 本模块当前正式范围已扩展到 `Step1-7`；未获当轮任务书授权，不得跨轮顺手推进其它步骤。
- 文档长期真相以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准；`README.md` 只承担操作者入口职责。
- 当前不新增 repo 官方 CLI；不要顺手修改 `entrypoint-registry.md` 发明新入口。
- 允许复用 T02 Stage4 的 Step2/3/4 内核，但禁止把 T02 的大一统 orchestrator 直接平移为 T04 主结构。
- `Step5-7` 正式研发默认遵循 SpecKit，任务书必须覆盖：
  - `Product`
  - `Architecture`
  - `Development`
  - `Testing`
  - `QA`
- 可以参考 T03 的实现逻辑、审计风格、产物形式与输出组织方式，但不得直接 import / 调用 / 硬拷贝 T03 模块代码；正式执行逻辑必须留在 T04 私有实现内。
- 优先按 `admission / local_context / topology / event_interpretation / support_domain / polygon_assembly / final_publish / review_render / outputs / batch_runner` 分层。
- Step4 review 图必须使用 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL`，不要用最终发布态标签冒充本阶段结论。
- 若 T04 文档与 T02/T03 正式契约冲突，先以当前任务书与线程 REQUIREMENT 为准，并在 handoff 中显式记录偏差。
