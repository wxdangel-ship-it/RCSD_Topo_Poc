# JunctionResult 输入输出合同

## 阶段可见性

| 阶段 | 可见 | 不可见 |
|---|---|---|
| Step1 | SWSD、DriveZone | RCSDIntersection、RCSD Node/Road、旧策略终态 |
| Surface | Step1 隐状态、SWSD、DriveZone、RCSDIntersection | 最终锚定与规则虚拟面成员真值 |
| Anchor | 全部允许的原始 RC 证据、已确定 surface 分支 | T03/T04/T05 终态 |
| Structured decode | encoder 嵌入、各模型头、合法候选 mask | 新增候选、修改 SWSD 路口身份 |

共享参数不能通过全证据聚合 token 绕过阶段可见性；Step1 的输入张量和 attention mask
必须有独立测试证明 RCSD 通道物理缺席。

## 输出不变量

1. `SUCCESS` 必须带完整 Node/Road 集合、唯一主锚定和可物化拓扑方案。
2. `NO_RCSD_EVIDENCE` 只能来自可证明的无证据监督或模型的低置信预测；后者发布前仍需
   安全门，不得自动派生现实冲突。
3. `AMBIGUOUS / QUALITY_ISSUE / ABSTAIN` 不得被后续 decoder 改写为成功。
4. structured decoder 只在已给候选中组合；候选 ID 与源对象必须可审计。
5. materializer 可拒绝非法方案，但不能另选对象或改变业务状态。

## 虚拟面验收

- 自动接受：所有 REQUIRED 对象均被关联/覆盖，所有 FORBIDDEN 对象均未被关联/覆盖。
- UNKNOWN 不计漏召回或误召回。
- Review 不进入自动发布和训练 loss。
- 旧规则面几何 exact 不作为成功条件；物化后拓扑仍是独立硬门。

## 等价比较

忽略生成 ID、文件顺序和无业务影响的折线点差异；严格比较 surface mode/关联对象、
锚定状态、源 Node/Road、主锚定、打断对象与顺序、Node 等价关系及最终拓扑。多个业务
正确方案通过 acceptable set 表达，非 preferred 的可接受方案不计错。
