# t04_divmerge_virtual_polygon 执行约束

- 本模块当前正式范围只到 `Step1-4`；禁止顺手推进 `Step5-7`。
- 文档长期真相以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准；`README.md` 只承担操作者入口职责。
- 当前不新增 repo 官方 CLI；不要顺手修改 `entrypoint-registry.md` 发明新入口。
- 允许复用 T02 Stage4 的 Step2/3/4 内核，但禁止把 T02 的大一统 orchestrator 直接平移为 T04 主结构。
- 优先按 `admission / local_context / topology / event_interpretation / review_render / outputs / batch_runner` 分层。
- Step4 review 图必须使用 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL`，不要用最终发布态标签冒充本阶段结论。
- 若 T04 文档与 T02/T03 正式契约冲突，先以当前任务书与线程 REQUIREMENT 为准，并在 handoff 中显式记录偏差。
