# 04 Solution Strategy

- 使用独立 `Step45` pipeline 承接冻结 Step3 之后的 RCSD 关联、`required / support / excluded` 分类与审计，不回灌 Step3
- `Step45` 结构拆分为 `step45_loader / step45_rcsd_association / step45_foreign_filter / step45_render / step45_writer`
- `Step45` 产出 `required / support / excluded` RCSD 集合、hook zone、状态与审计；兼容性 foreign context 文件仍保留，但不再承担 `Step6` hard subtract 语义
- 使用独立 `Step67` pipeline 承接 `Step6` 受约束几何与 `Step7` 最终发布，结构拆分为 `step67_geometry / step67_acceptance / step67_render / step67_writer / step67_batch_runner`
- `Step67` 的 solver 细节继续留在实现与 closeout，不把 `20m`、buffer、ratio 等常量提升为长期契约
- `Step7` 主状态收敛为 `accepted / rejected`；视觉审计继续沿用 `V1-V5`
- 当前 `Step67` 正式交付通过模块内 `run_t03_step67_batch()` 维持，不在本轮新增 repo 官方 CLI
