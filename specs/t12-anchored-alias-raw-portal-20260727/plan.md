# Plan：T12 anchored canonical alias raw portal

## 1. 范围

只修改 T12 portal、审计输出、正式源事实与测试。T01–T11、入口参数、FRCSD 输入和历史 run 均不改变。

## 2. 实施顺序

1. 以测试固定 mainNode→subNode raw endpoint、Direction role 和 spatial fallback 边界。
2. 让 `raw_portal_candidates` 接收 canonicalizer/canonical groups。
3. 从 anchor `base_id` 解析 selected canonical ID并展开 raw group；其它显式 grouped raw node不递归扩组。
4. 对 anchored alias 应用 outgoing/incoming 强过滤，距离只记录。
5. 保留 T07 标准面与 T03/T04 半径 spatial fallback，且不得跨 anchored canonical group放宽。
6. 增加 portal 来源/距离角色审计并升级 schema。
7. 同步项目级与模块级正式源事实。
8. 运行自动化、真实 Case、静态与体量检查。

## 3. 风险控制

- 大 canonical group 可能扩大 portal：只展开 T05 选中 `base_id` 所属 group，并继续要求当前方向出/入边；禁止递归展开其它 grouped node 的 group。
- alias group 不能形成零成本 carrier：路径仍在 raw identity graph 上搜索，必须有物理 Road。
- spatial fallback 误接边：维持既有半径/标准面规则。
- 性能：canonical groups 已在全图预构建，不增加全图级重复扫描。

## 4. 回滚

本变更集中于 T12 portal 构造与 schema；可通过回滚单次提交恢复 v5，不修改任何输入数据。
