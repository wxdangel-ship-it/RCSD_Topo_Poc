# P12R Validation Summary

## 1. 结论

正式decision：

`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`

Gate 0/1/2/4通过；Gate 3因最差Case-grouped fold candidate oracle recall低于
0.90而失败。该结论表示条件化真值和安全构图合同成立，但当前5m局部候选生成需要
补强；不表示神经网络整体不适用，也不授权训练P13。

## 2. 正式双跑

- Run A：
  `p05_scheme_a_p2_p3_p12r_advance_right_audit_20260724_03`
- Run B：
  `p05_scheme_a_p2_p3_p12r_advance_right_audit_20260724_04`
- 共同content signature：
  `320a8216a3e3592c9037f32300af7162b10d615277130d132bd410bb68e825e7`
- Run B `reference_run_match=true`

## 3. 业务与安全指标

- AdvanceRight：474个，6个Case，5个Case-grouped fold；
- `access_valid=false`：40个，全部`REVIEW_FALLBACK`；
- 自动条件化真值：396个，两侧required/realized source一致396/396；
- T05提右anchor label：0；
- T06终态推理候选：0；
- RCSD缺失误报RealityChangeClue：0；
- 挂接关系缺失：0；
- 正式Segment独立Road丢失：0；
- unsafe auto publish：0；
- Movement decision、骨架mutation、geometry write、silent fix：均为0。

## 4. 候选上限

- eligible：396；
- oracle hit：377；
- 总体recall：`0.952020`；
- 最差fold：T10:706247，`21/24=0.875`；
- 19个漏候选均为`RCSD_ONLY`：
  - T10:1885118：12；
  - T10:605415675：1；
  - T10:609214532：3；
  - T10:706247：3。

其中17个正确RCSD有直接lineage，但距原SWSD提右为`5.15–43.55m`；另2个缺少可
直接消费的原始RCSD lineage。下一阶段应使用Road endpoint/JunctionUnit及相邻普通
Segment carrier条件化扩召回，不得直接把5m放宽为业务强规则。

## 5. 测试、GIS、资源与体量

- P12R专项测试：5 passed；
- 完整P05回归：253 passed；
- CRS一致且为米制：474/474；
- Run A/B wall：约22.12/22.29s；
- Run A/B峰值RSS：约0.417/0.416GiB；
- GPU/训练：0；
- 新增源码/测试体量：
  - `scheme_a_p2_p3_p12r_audit.py`：61,410 bytes；
  - `scheme_a_p2_p3_p12r_models.py`：3,291 bytes；
  - `test_scheme_a_p2_p3_p12r.py`：4,817 bytes。

全部低于100KB硬阈值。本轮未修改T01–T12、未新增正式入口、未提交或推送Git。
