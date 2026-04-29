# Tasks

- [x] 产品：确认 `related / local_required / foreign_mask` 三层业务含义。
- [x] 架构：确认保留旧文件名，新增 status/audit 字段，不改入口。
- [x] 研发：Step4 新增 related 字段，并将 outside-scope continuation 收敛为 required-core 一跳补证。
- [x] 研发：Step4 将多点 `mainnodeid` RCSD 复合语义组扩展为 related node，并禁止自动扩展全部 group incident road。
- [x] 研发：Step5 从 hard negative 中排除 related road，新增 `foreign_mask_source_rcsdroad_ids`。
- [x] 研发：Step6 暴露三层字段，保持 existing must-cover / acceptance 判定。
- [x] 研发：review PNG 深红 RCSDRoad 改为强语义 related / required 口径，support 保持 amber。
- [x] 测试：新增 remote outside-scope road 不进入 related、应进入 foreign mask 的 synthetic 与真实 case 回归。
- [x] 测试：新增 synthetic multi-node RCSD group 不自动拉入 unrelated incident road 测试。
- [x] 测试：新增 association render related 口径测试。
- [x] 测试：补 706389 三层语义回归断言。
- [x] 测试：补 705817 多点 RCSD 复合语义路口回归断言。
- [ ] QA：运行 broader regression 并确认无 Step3/Step7/entrypoint 回退。
