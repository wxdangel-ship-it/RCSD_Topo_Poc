# clarify

## 为什么先做 S3-B
- 审计结论已经冻结：主簇是 S3-B + S3-C，但 S3-B 的问题更基础，表现为 Step3 直接把 patch 内 DriveZone 当 allowed space，trunk 没有 frontier / stop。
- 在没有 Step3 收口之前，后续 Step5 / Step6 / Step7 的任何收尾都在一个过宽的上游空间里工作，先修 S3-B 才有意义。

## 为什么 758888 / 793460 / 10970944 足够代表 S3-B
- 758888：single_sided_t_mouth，是最典型的 trunk 应该有停点却没有停点的样板。
- 793460：center_junction，是 RCSD 表达差异 / 约束不足时 Step3 仍应独立定义 stop condition 的对照样板。
- 10970944：center_junction 且当前路径稳定，是复核 shadow frontier 是否能在非 failure case 上同方向改善的代表样本。

## 为什么 accepted 样本必须保护
- 本轮目标不是直接提升 accepted，而是证明 shadow Step3 的方向正确。
- 如果 shadow 收口靠牺牲当前 accepted 样本才能成立，说明 frontier 规则仍然没有达到可进入正式切换轮的成熟度。

## 为什么本轮暂不打 S3-C
- S3-C 的核心是 corridor binding / required support 完成后 trunk 仍可外推，这已经接近正式 Step3/Step4 边界定义。
- 当前第一轮只需要先证明：即便只补最基础的 directional frontier / stop，legal space 也能明显收口，而且不误伤 accepted。
