# P12R-R1 验证摘要

## 结论

正式decision为：

`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`

R1关闭P12R的endpoint/Junction条件化候选可达性阻断。该结论只证明候选集合具备
下一阶段训练前提，不授权训练、自动发布、生产接入或修改T01–T12。

## 正式运行

- Run A：`p05_scheme_a_p2_p3_p12r_r1_endpoint_candidates_20260724_01`
- Run B：`p05_scheme_a_p2_p3_p12r_r1_endpoint_candidates_20260724_02`
- candidate frozen signature：
  `84344d11cdc168cea42cdaacd0c36f83f9f4b57e45dd01b802a9c35ce064f734`
- content signature：
  `244b81957cf4eb39889fd88b61bdccb296707a901f8240580c46061aeb2a1e5b`
- Run B `reference_run_match=true`
- 两轮各8个artifact的SHA-256与size自校验：`mismatch=0`

## 产品与业务验收

- 冻结P12R对象数：`474/474`
- eligible对象：`396`
- Control精确复现P12R：`474/474`
- Control/Treatment Oracle命中：`377/388`
- Control/Treatment recall：`0.952020/0.979798`
- Treatment相对Control gain/loss：`11/0`
- 最差Treatment fold：`0.916667`，门槛`>=0.90`
- 五个fold均无下降

## 架构与安全验收

- 候选冻结前label read：`0`
- truth feature、T05提右label、T06 candidate/feature：`0/0/0`
- case hardcode、cross-case candidate：`0/0`
- endpoint evidence不完整候选自动加入：`0`
- ambiguous orientation候选自动加入：`0`
- geometry write、Movement decision、training：`0/0/0`
- unsafe auto publish、T01–T12 modification：`0/0`
- 候选数P95/max：`4/12`，门槛`<=10/32`
- 6/6 Case输入CRS一致且为米制投影

## 研发与测试验收

- R1专项测试：`4 passed`
- 完整P05回归：`257 passed`
- `py_compile`：通过
- P05源码与测试文件：`204`
- `>=100KB=0`、`>=60KiB=0`
- R1新增models/candidate/audit/test体量：
  `2086/14997/31577/5154` bytes
- 未新增CLI、script、`__main__.py`、Makefile或T10 stage

## 性能与可追溯性

- Run B wall：`13.7255s`
- Run B peak RSS：`446832640` bytes
- GPU required：`false`
- 每个正式run保存candidate、delta、endpoint evidence、fold、metrics、summary、
  input manifest、artifact manifest和validation report

## 待后续授权

下一阶段可讨论冻结R1候选后的object-conditioned candidate scorer、拒识/fallback和
RoadGraph安全验收。R1的`1m/5m/10m`只属于候选发现合同，不得解释为业务锚定或
最终替换合法性。
