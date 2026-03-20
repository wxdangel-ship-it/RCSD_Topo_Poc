# 11 风险与技术债

## 当前主要风险
- repo 级治理文档尚未把 `t01_data_preprocess` 正式登记为 Active 模块，存在“模块内 accepted baseline 已形成，但仓库级状态未同步”的治理差口。
- `step2_segment_poc.py` 当前体量已超过仓库建议阈值，后续继续演进存在结构债风险。
- 当前三样例活动基线虽然已覆盖通用、距离 gate、环岛三类场景，但仍不是完整生产规模验证。

## 当前可接受技术债
- 旧单样例 freeze 和旧 semantic-fix candidate 仍保留为历史目录。
- `architecture/overview.md` 同时承担目录索引与概览说明，后续若模块正式激活，可再进一步细化。

## 后续缓解方式
- 后续若正式启动模块治理，应同步补 repo 级模块清单与 doc inventory。
- 在不破坏当前活动基线的前提下，逐步拆分超大源码文件。
- 后续性能优化必须持续对齐三样例活动基线。
