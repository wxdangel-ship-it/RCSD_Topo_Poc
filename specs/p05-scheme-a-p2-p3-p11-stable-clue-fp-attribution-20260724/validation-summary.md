# P05-Scheme-A-P2-P3-P11 验证摘要

## 阶段结论

- decision：`P05_SCHEME_A_P2_P3_P11_REVIEW_REQUIRED`
- 人工目视结果已正式接受，20个稳定Clue FP已有对象级1.0真值，30个低风险对象
  仍只有T10 Case级0.7真值；
- 不表示神经网络不适用，不授权训练、调阈值或修改carrier/RoadGraph；
- 稳定Clue漏报为`0`、错误自动发布为`0`，本阶段没有发现新增安全放行风险；
- 19/19首轮目视对象均确认`RealityChangeClue=false`，证明当前Clue head稳定
  过度保守，正在阻止可安全使用的RCSD。

## 正式双跑

- 基准运行：
  `outputs/_work/p05_neural_road_generation/p05_scheme_a_p2_p3_p11_clue_fp_audit_20260724_06`
- 复现运行：
  `outputs/_work/p05_neural_road_generation/p05_scheme_a_p2_p3_p11_clue_fp_audit_20260724_07`
- content signature：
  `7506b98ff1a2b91e4e789f498f5619688a4a64e88a85d4ebfb131e3409d6205d`
- reference run match：`true`
- wall：`16.78s / 16.68s`
- peak RSS：`357540 / 355864 KiB`
- GPU、训练、阈值调整、模型权重修改：均为`0`

`20260724_01`与`20260724_04`为空的失败预检目录，分别暴露dict-style manifest与
Windows/WSL manifest路径兼容问题；没有形成有效审计工件。正式证据只认
`20260724_06/07`。

### 人工裁决接受双跑

- 基准/复现：
  `p05_scheme_a_p2_p3_p11_review_acceptance_20260724_02/03`
- decision：`P05_SCHEME_A_P2_P3_P11_MANUAL_REVIEW_ACCEPTED`
- signature：
  `9c8a326da9899ef27a5e35ad40d1dd024e2d3baf3ad643c5e15b75eb8aa236c6`
- 19行非填写字段漂移：`0`
- 与既有P10五对象合并后对象级1.0真值：`24`

### 24对象P10复算双跑

- 基准/复现：`p05_scheme_a_p2_p3_p10_adjudication_20260724_05/06`
- decision：`P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`
- content signature：
  `bda2f4899a1402420e6db010668869e955e30fc03d915e56fb3626fcf2fcd145`
- carrier safety gate：`true`
- promotion gate：`false`

### 裁决后P11双跑

- 基准/复现：`p05_scheme_a_p2_p3_p11_clue_fp_audit_20260724_08/09`
- content signature：
  `41d75f1a87eddfb63ad641b09e8b3d58e7b424777ca463f54f715d210fb52e7d`
- reference run match：`true`

## 业务计数

- Control/Treatment稳定Clue FP：`50 / 50`
- Control/Treatment稳定Clue FN：`0 / 0`
- 已有对象级1.0人工真值：`20`
- 仍只有Case级0.7真值：`30`
- 当前风险规则下新增人工目视队列：`0`
- 已完成首轮人工目视：`19`，覆盖`3`个Case
- 队列分布：
  - `T10:1885118`：`7`
  - `T10:706247`：`9`
  - `T10:991176`：`3`

## 人工裁决与模型结果

- 19个对象全部：`RealityChangeClue=false`
- 只允许且优先`USE_RCSD`：`12`
- 只允许且优先`KEEP_SWSD`：`7`
- 12个`USE_RCSD`均由用户确认两侧路口可正确锚定，且替换后的Road连接正确；
- 7个`KEEP_SWSD`均为RCSD全部或局部缺失，不构成现实道路结构冲突。

冻结P9在19对象、两arm、三seed上共形成114条决策：

- carrier合法：`78/114 = 0.6842`
- 19对象中所有arm/seed均选对carrier：`11`
- 至少一个seed选错carrier：`8`
- Clue判断正确：`0/114`
- 自动接受：`0/114`
- 错误自动发布：`0`

因此安全策略有效，但自动化被完全挡住。Control与Treatment结果相同，现有
carrier-only source residual adapter没有带来增益。

## 人工定位QA

- 15个普通Segment均可在QGIS `segment`图层按T01 `id`定位；
- 4个`ADVANCE_RIGHT`均可在`prepared_swsd_roads`按SWSD Road ID定位，
  且source/target access完整、`access_valid=true`；
- 19/19 locator均实际命中；
- 涉及的T01 Segment与prepared SWSD Road图层CRS均为`EPSG:3857`；
- 只核验属性ID、图层路径和CRS，geometry read/write均为`0`，没有silent fix。

## 回归

- P11专项测试：`3 passed`
- P05完整回归：`248 passed`
- P05 `src/`与两处`tests/`：`197`个Python文件；
- `>=60KiB=0`、`>=100KB=0`，最大仍为`scheme_a_baseline.py`的`58135 bytes`；
- P11实现/测试：`51496/16350 bytes`；
- 未新增CLI、script、`__main__.py`、Makefile target或T10 stage。

## 后续结论

当前不需要用户继续审核剩余30个低风险对象。下一阶段应先设计显式
endpoint/Junction anchor eligibility，再修正Clue head对“现实结构冲突”与
“RCSD缺失/不确定”的区分；P11保持`REVIEW_REQUIRED`仅表示30个对象尚未获得
对象级1.0真值，不表示当前19对象裁决未完成。
