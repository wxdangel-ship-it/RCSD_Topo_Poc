# 11 Risks And Technical Debt

## 当前风险

- T07 从 T02 Step1 / Step2 继承业务语义，但不能继承 T02 的 Segment 候选域；实现时若复用 T02 代码过多，容易重新引入 Segment 依赖。
- `mainnodeid = 0` 在不同模块存在不同解释边界；T07 当前按 T02 口径只声明空值 singleton，如需把 `0` 视为空值必须另行确认。
- `kind_2 = 64` 当前在 Step2 中写 `no / NULL` 并交由后续专项规则处理；若专项规则落地，必须另行同步契约。
- `kind_2 = 128 / 2048` 当前 Step2 仍写 `no / NULL`；Step3 只在 T05 `intersection_match_all` 已发布成功 relation 时补写 anchor，不反推 128/2048 的 RCSDIntersection surface 语义。
- `kind_2 = 2048` 不参与或接收 Step2 `fail2`；如 T03 对 T 型路口虚拟锚定口径变化，必须同步 T07 Step3 relation backfill 边界。
- Step3 依赖 T05 `intersection_match_all.geojson` 的 `target_id / base_id / status` 规格；若 T05 relation 字段或 CRS 规格变化，必须同步 T07 契约与测试。
- Step3 只校验 RCSD `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在，不反推 RCSD 语义路口字段含义。
- Step3 合并 `t07_swsd_rcsd_relation_evidence.csv/json` 时默认从 Step2 `nodes.gpkg` 同目录读取 Step2 evidence；若用户传入非 Step2 目录的 nodes，需要确认合并基准是否存在。
- Step3 复制 `t07_rcsdintersection_anchor_surface.gpkg` 时同样默认从 Step2 `nodes.gpkg` 同目录取源；若缺失 Step2 surface，只能输出空 surface 并通过 `anchor_surface_write_mode` 暴露。

## 技术债控制

- 首轮实现应保持小文件分层，避免复制 T02 大文件。
- 测试应拆分为 Step1/Step2、Step3 与 no-Segment dependency，不集中到单个超大测试文件。
- 除已登记的内网脚本外，若后续新增入口，必须先走入口治理并同步 registry。
