# P05-Scheme-A-P2-P3-P13-P0 验证摘要

## 1. 正式结论

P13-P0训练、OOF评价、正式双跑和安全验收已完成，阶段decision为：

`P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`

这表示R1候选集合已经基本包含正确carrier，但当前只依赖候选关系与几何的
50维表征，不能在held-out Case上可靠选择正确Road子集，也不能满足自动发布
零错误门。本结论不否定神经网络路线；它否定的是把现有candidate-only scorer
直接接入提右自动替换。

## 2. 正式运行

- Run E：`outputs/_work/p05_neural_road_generation/p05_scheme_a_p2_p3_p13_p0_oof_20260724_05`
- Run F：`outputs/_work/p05_neural_road_generation/p05_scheme_a_p2_p3_p13_p0_oof_20260724_06`
- 对象：474个ADVANCE_RIGHT Segment，其中396个eligible；
- 模型：candidate encoder + mean/max set pooling + candidate/object/safety heads；
- 参数量：480,739；
- OOF：3 seeds `17/29/43` × 5 Case folds，共15个checkpoint；
- feature signature：
  `949d15ff4d0a87cce8c1be0f742aa921110e08baf6a288af7b38730f6c9c4e53`；
- content signature：
  `c219be6609e0bc0a9dfccb9077a2a19de20f23fc10059839313dd28679fa3925`。

Run F相对Run E的`reference_run_match=true`；两个run各27个受审计工件，
manifest mismatch为0，15个NPZ checkpoint逐字节hash一致。

## 3. Gate结果

| Gate | 结果 | 证据 |
| --- | --- | --- |
| Gate 0 范围与lineage | PASS | 474对象、6 Case、15个fold模型完成；R1 candidate signature精确匹配；T01–T12 modification=0 |
| Gate 1 防泄漏 | PASS | feature冻结前label read=0；ID、绝对坐标、路径、Case/fold、Movement及T05/T06终态进入特征均为0 |
| Gate 2 模型与选择能力 | FAIL | pooled raw exact-set=`0.6469`，低于5m Local Control的`0.6804`；最差fold=`0.3636`；candidate macro-F1=`0.7510`；object macro-F1=`0.7914` |
| Gate 3 自动发布安全 | FAIL | accepted coverage=`0.0177`、最差fold=`0`；unsafe auto RCSD=`14`，Review auto RCSD=`2`，R1不可达auto RCSD=`1` |
| Gate 4 确定性、GIS、资源 | PASS | 双跑内容签名一致；6/6 Case CRS一致且为米制；无geometry写入/变换/silent fix；CPU训练和完整回归通过 |

## 4. 资源与回归

- Run E：15模型训练wall `31.419s`，总wall `47.929s`，
  peak RSS `414,916,608 bytes`；
- Run F：15模型训练wall `32.603s`，总wall `47.988s`，
  peak RSS `414,519,296 bytes`；
- GPU：未使用；
- P13专项测试：`5 passed`；
- 完整P05回归：`262 passed`；
- 新增P05源码与测试均小于60KiB和100KB硬阈值。

## 5. 失败归因

在3 seeds × 388个eligible且R1 Oracle可达对象上：

- 模型与Local Control都正确：730；
- 模型与Local Control都错误：349；
- 仅Local Control正确：62；
- 仅模型正确：23。

跨3个seed稳定的对象中，稳定错误116个，稳定正确229个；Local Control稳定正确
但模型稳定错误6个，模型带来稳定增益3个。错误不是由正确carrier缺失主导，而是
当前表征无法观察提右carrier选择所依赖的相邻普通Segment替换状态。

## 6. 业务解释与后续边界

普通提右不是独立经过T05锚定后直接选择carrier。它的两侧应随相邻普通Segment
最终采用RCSD或SWSD而选源，必要时还要在不同数据源之间执行确定性几何衔接，并
处理挂接Segment。P13-P0只看提右自身候选关系与几何，因此缺少决定正确选择的
关键条件。

下一阶段合理目标是先审计：能否把相邻普通Segment的OOF软carrier状态作为
推理期可用、无终态泄漏的联合条件输入。该审计尚未授权；在审计通过前，不应
继续调参、扩大当前candidate-only网络或启动P13-P1训练。
