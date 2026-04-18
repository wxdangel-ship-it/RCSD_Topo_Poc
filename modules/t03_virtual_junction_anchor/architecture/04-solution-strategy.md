# 04 Solution Strategy

- 使用独立 `Step45` pipeline 承接冻结 Step3 之后的 RCSD 关联、`required / support / excluded` 分类与审计，不回灌 Step3
- `Step45` 结构拆分为 `step45_loader / step45_rcsd_association / step45_foreign_filter / step45_render / step45_writer`
- `Step45` 产出 `required / support / excluded` RCSD 集合、hook zone、状态与审计；兼容性 foreign context 文件仍保留，但不再承担 `Step6` hard subtract 语义
- 使用独立 `Step67` pipeline 承接 `Step6` 受约束几何与 `Step7` 最终发布，结构拆分为 `step67_geometry / step67_acceptance / step67_render / step67_writer / step67_batch_runner`
- 对 `single_sided_t_mouth + association_class=A`，Step67 的横方向口门不再使用纯投影启发式：
  - 先从竖方向候选空间内的相关 `RCSDRoad / chain` 建 tracing seed
  - 再向横方向追踪并确认落在横方向候选空间内的 terminal `RCSDNode`
  - 以 terminal `RCSDNode` 为主锚点外扩 `5m`
  - 若 tracing 无法在横方向两侧都确认 terminal `RCSDNode`，则回到 generic directional boundary
  - 并在前方其他直接关联语义路口处提前停止
- 对冻结 `Step3` 已应用 `two_node_t_bridge` 的 `single_sided_t_mouth` case，Step67 不再把该 bridge 仅视为上游 allowed-space 历史事实，而是显式继承为 directional boundary / polygon_seed 的中心桥接支撑，保证横方向口门裁剪后中心仍保持连通
- `Step67` 的 solver 细节继续留在实现与 closeout，不把 `20m`、buffer、ratio 等常量提升为长期契约
- `Step7` 主状态收敛为 `accepted / rejected`；视觉审计继续沿用 `V1-V5`
- 当前 `Step67` 正式交付通过模块内 `run_t03_step67_batch()` 维持，不在本轮新增 repo 官方 CLI
