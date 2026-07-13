# T10 工作流增加 T11 阶段规格

## 背景

T10 Case runner 与 innernet full pipeline 当前在 T06 后直接进入 T09，未把已正式建立的 T11 relation repair candidate 抽取纳入端到端审计链。用户授权修正正式流程，并同步相关源事实、契约、入口登记、测试与治理文档。

## 目标流程

- Case runner：`T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 Step1/2 -> T06 Step3 -> T11 -> T09 Step1/2 -> T09 Step3`。
- Innernet full pipeline：`T08（可选前置） -> T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 Step1/2 -> T06 Step3 -> T11 -> T09`。
- T07 Step3 继续保持显式可选兼容阶段，不纳入默认主链。

## 范围

### 包含

- 在既有 `scripts/t10_run_e2e_cases.sh` 对应 Case runner stage graph 中增加 `t11`。
- 在既有 `scripts/t10_run_innernet_full_pipeline.sh` 中增加 `t11`，同步 resume、`RUN_STAGES`、manifest、summary 和 finalize 完成判定。
- T11 使用既有 `scripts/t11_extract_relation_repair_candidates.py` 单用例模式，不新增执行入口。
- 同步 T10/T11 模块源事实、架构、入口登记、体量审计与测试。

### 排除

- 不修改 T01-T09、T11 的业务判定规则。
- 不让 T11 输出回写或改变 T09 输入；T09 继续消费 T06 F-RCSD 与既有 SWSD handoff。
- 不把 T11 人工结果自动回灌 T05/T06。
- 不运行 T08 作为 Case runner 默认阶段。

## 阶段契约

- `t11` 必须在 `t06_step3` 通过后执行；T06 失败或阻断时，T11 与 T09 均阻断。
- Case runner 的 T11 输入根为当前 `case_run_dir`，输出为 `cases/<case_id>/t11/run_<timestamp>/`。
- Innernet full pipeline 的 T11 输入根为当前 `RUN_ROOT`，输出为 `<RUN_ROOT>/t11_manual_relation_review/run_<timestamp>/`。
- T11 正式产物至少包括 candidates CSV 与 summary JSON；缺失时该阶段不得标记为 passed。
- T11 是审计阶段，不向 T09 发布业务输入 handoff。

## 完成口径

- 新 T10 run 只有在 T11 与 T09 均成功且必要最终产物存在时才可标记 passed。
- 既有 legacy full run 若缺 T11，不再仅凭 T06/T09 执行 `FINALIZE_EXISTING` 得到新口径 passed；应先用 `RUN_STAGES=t11` 补跑并登记 T11，再 finalize。
- `STOP_AFTER=t11`、`RESUME_FROM_STAGE=t11` 与 `RUN_STAGES=t11` 必须可用。

## 五类职责视角

### 产品

- T10 端到端结果中可直接定位 T11 候选审计产物，不再需要运行后手工补抽取。

### 架构

- T11 位于 T06 与 T09 之间，但保持 audit-only；不改变 T06→T09 的业务数据依赖。
- 复用现有入口，不新增 CLI 或脚本。

### 研发

- Case runner 使用独立 stage adapter，避免把接近 60KiB 的 `case_runner_pipeline.py` 继续膨胀。
- 所有源码/脚本写入前检查体量，变更后保持低于 61,440 字节。

### 测试

- 覆盖 stage order、stop-after、T11 command、输入缺失阻断、输出发现、innernet resume 顺序与 manifest 字段。
- 先以 `1885118` 验证，再回归六用例。

### QA

- CRS、坐标、拓扑和几何不由 T10/T11 runner 修改，不允许 silent fix。
- manifest 记录 T11 输入根、输出、日志、状态与耗时。
- T11 失败不得提升部分产物，也不得继续同一 Case 的 T09。
- 性能通过阶段 duration 和完整 run 增量可验证。

## 验收标准

1. 两条正式 T10 runner 的顺序均为 `T06 -> T11 -> T09`。
2. 原 T10 与 T11 正式入口路径保持不变，无新增入口。
3. `t11` 支持 stop/resume/exact-stage 执行并写入 manifest/summary。
4. T11 输出不进入 T09 业务参数，T09 业务结果不因编排插入而改变。
5. `1885118` 和六用例回归中 T11 产物完整，Case stage order 正确。
6. T10/T11 定向测试、shell syntax、compile 和治理审计通过。
7. 本轮涉及源码/脚本均低于 61,440 字节。
