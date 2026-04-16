# spec

- 本轮是 Step3 S3-B shadow repair。
- 本轮只冻结 S3-B 的 Step3 需求候选，并实现 default-off 的 shadow frontier / stop 验证路径。
- 非目标：不切正式主路径、不处理 S3-C、不修改 Step5 / Step6 / Step7 正式业务逻辑、不改变 default baseline 结果。

## 成功标准
- test_anchor61_baseline.py 继续 61/61 通过。
- 默认路径 formal 结果不变。
- 758888 / 793460 / 10970944 的 shadow legal space 显式收口，并生成 frontier / stop 输出。
- 当前 accepted 保护样本在 shadow 下不出现明显反常收缩。
