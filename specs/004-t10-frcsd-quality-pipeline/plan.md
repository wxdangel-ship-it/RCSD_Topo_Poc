# Implementation Plan: T10 FRCSD 质量检查专用流水线

## 产品视角

- 提供一个名称和用途明确的正式脚本，减少内网使用者对 `RUN_T08/RUN_T12` 和 stage 顺序的手工配置。
- 输出继续区分 T11 relation review、T12 FRCSD quality audit 和 T09 restriction。

## 架构视角

- 复用既有 T10 full runner 作为唯一编排实现；新入口只冻结 profile、默认 run root 和冲突前置检查。
- 默认 T10 v1 常量保持不变；新增 T12 的链常量/顺序改为 T11 后、T09 前。
- T09 handoff 不变，避免审计阶段侵入正式数据生产。

## 研发视角

1. 调整 Case runner 的 `WITH_T12` stage/chain 顺序。
2. 在 full runner 中移动 T12 stage 到 T11 后，并同步 resume/stage index/manifest pipeline。
3. 新增薄脚本 `t10_run_frcsd_quality_pipeline.sh`，强制 `RUN_T08=0/RUN_T12=1` 后 `exec` full runner。
4. 同步 T10/T12/项目合同和入口登记。

## 测试视角

- 单元/合同测试：默认顺序、专用顺序、wrapper 固定变量、冲突阻断、显式 FRCSD slots。
- 运行测试：shell syntax、CLI help、T10/T12/T06 相关测试。
- 端到端：复用 1026960 Case package 运行新顺序，比较 T06/T11/T09 工件并核对 T12 35/10/25/0。

## QA 视角

- CRS、拓扑、几何、输入路径、指纹、阶段耗时和 `silent_fix=false` 保持可定位。
- 扫描生产源码，确保无对象级 ID 白名单。
- 更新 entrypoint registry 和 code-size audit；新旧脚本均低于治理阈值。

## Risks

- T12 移到 T11 后可能被误解为消费 T11 输出；合同必须明确只改变执行顺序，不新增数据依赖。
- full runner 接近 60 KiB；本轮只移动既有代码并做等长/缩减修改，不向主脚本回填 wrapper 逻辑。
- 内网完整数据不可本机执行；本地只验证用例和入口合同。
