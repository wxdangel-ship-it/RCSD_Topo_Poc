# 实施计划

## 1. specify

- 冻结T03/T04现有label-only角色、T06前生成时点和T05 handoff语义。
- 冻结字段白名单、禁止字段与T01 `junc_nodes`唯一join口径。
- 分开冻结carrier与Clue来源门。

## 2. plan

1. 校验P7、Dataset-P0、T01/T03/T04登记工件及模块源事实hash。
2. 为51个eligible Case冻结T03/T04核心正式工件清单和内容hash。
3. 解析T01 `junc_nodes`，构建6,275对象Case-local applicability ledger。
4. 对T03/T04正式字段执行whitelist/blacklist审计。
5. 构建不含ID/坐标/path/reason/truth、且对T04 merge/diverge方向不变的carrier
   source signature；方向字段继续保留为独立上下文候选。
6. 对稳定carrier wrong执行held-out-fold train-only同签名审计。
7. 对2个稳定FP、4个稳定FN执行来源覆盖审计。
8. 完成正式Run A/B、专项测试、完整P05回归、资源/体量/入口审计。
9. 同步P05与项目源事实，形成字段promotion是否值得二次授权的结论。

## 3. implement边界

- 新增P05内部：
  - `scheme_a_p2_p3_p8_models.py`
  - `scheme_a_p2_p3_p8_audit.py`
  - 对应测试与模块导出
- 不修改T03/T04实现、接口或正式工件。
- 不新增执行入口，不训练模型，不修改T01–T12。

## 4. 验证

- whitelist/blacklist、Case-local join、applicability、签名与decision纯函数测试；
- 正式Run A/B；
- 完整P05回归；
- hash、CRS、无泄漏、资源、体量与入口审计。
