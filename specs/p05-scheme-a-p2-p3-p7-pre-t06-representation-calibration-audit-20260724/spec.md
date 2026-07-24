# P05-Scheme-A-P2-P3-P7：T06 前关系表征与 Clue 校准合同审计

## 1. 状态与授权

- 状态：已完成，`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`
- 授权日期：2026-07-24
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 输入：既有 P05 冻结工件与 `E:\TestData\POC_Data`
- 训练与调参：禁止
- T01–T12：不修改实现或接口
- Git：不提交、不推送
- Movement：忽略

本阶段承接
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`，只回答当前合法
T06 前来源是否足以支持下一轮训练。P5/P6 原始工件不得改写。

## 2. 阶段目标

1. 从既有 T01、T07、truth-free proposal 和 Segment→Node compatibility 建立
   translation/rotation-invariant 的关系与共享上下文表征；
2. 审计新表征是否改变 P6 稳定 carrier wrong 和稳定 clue FP/FN 的训练邻域；
3. 冻结与 carrier rank 解耦、严格 inner-validation-only 的 clue 校准合同；
4. 证明单一单调 probability calibration 是否可能满足 clue 门；
5. 判定是否已有技术依据申请下一轮模型训练，或必须先扩大合法推理来源。

## 3. 冻结来源语义

1. 允许：T01 Segment 属性/相对几何、T07 `DRIVEZONE_ONLY`、truth-free proposal
   candidate/payload、Segment→Node compatibility、P5 OOF score lineage。
2. T01 几何只允许派生长度、曲率、方向离散度、相邻角度等平移/旋转不变量；
   不输出绝对坐标，不把 Segment ID 作为 feature。
3. compatibility/node/Segment ID只用于 Case 内关系 join，输出仅保留计数和聚合量。
4. T03/T04/T05/T06 当前继续 `label-only`，不得进入新表征。
5. truth、label、held-out Case统计不得进入 representation；只允许在审计层评价。
6. 不改 T01 Segment/Junction 骨架，不生成或修改 RoadGraph。

## 4. 五类职责视角

### 产品

- 本阶段成功标准是明确“当前来源够不够”，不是必须得到正向 GO。
- 安全优先，不得用 held-out 标签选择 feature、阈值或 cohort。

### 架构

- 表征分为 base-202、compatibility-neighborhood 和 T01 relative-geometry 三块。
- 历史 base-202 只读保留；P7 明确剔除其中 14 个实际非零的
  `MOVEMENT_DEGREE` / `CONTEXT_MOVEMENT_DEGREE` 命名维度，并同步剔除
  它们派生的 28 个邻域聚合维度。
- clue 校准与 carrier scorer 解耦，外层 held-out Case不得参与拟合或阈值选择。
- 如果当前来源仍不可分，必须输出 source-role 阻断点，不得读取 T06 终态绕过。

### 研发

- 只新增 P05 内部 schema、representation/audit callable、测试和 SpecKit。
- 不新增 CLI、script、T10 stage、`__main__.py` 或 Makefile target。
- 不训练模型、不拟合 calibrator、不改历史工件。

### 测试

- 覆盖相对几何不变量、Case 内邻接、零邻居和身份不进入 feature。
- 覆盖 held-out fold train-only 邻域、单调阈值可行性和校准池隔离。
- 覆盖正式 Run A/B、完整 P05 回归、hash/CRS/资源/体量。

### QA

- 输入、CRS、feature contract、lineage、输出和环境可定位。
- geometry read 只计审计读取，geometry write与coordinate transform必须为0。
- Run A/B 规范化 signature一致。

## 5. 验收门禁

### Gate 0：来源与范围

- P6 decision精确为
  `P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`；
- P5/P6、Dataset-P0、P2-P1 dataset和202维evidence全部manifest/hash通过；
- 6,275/6,275 eligible对象具有T01相对几何，CRS均为`EPSG:3857`；
- truth/identifier/absolute-coordinate/T03–T06/Movement feature均为0。

### Gate 1：新表征

- 每对象输出602维：
  `188 movement-free base + 377 compatibility-neighborhood
  + 37 relative-geometry`；
- feature全部finite，group重复/missing为0；
- compatibility邻接和T01共享节点邻接只在Case内；
- geometry write、coordinate transform、skeleton mutation均为0；
- Run A/B representation signature一致。

### Gate 2：可分性

- 对P6的2个稳定FP、4个稳定FN执行held-out-fold train-only top-20审计；
- held-out Case进入邻域数为0；
- stable carrier wrong 的top-20至少出现1个`KEEP_SWSD`且至少1个`clue=true`，
  才允许判定当前表征路线通过；
- 若仍为`20/20 USE_RCSD + 20/20 clue=false`，当前来源路线必须NO-GO。

### Gate 3：Clue 校准合同

- 每个outer fold的inner calibration pool均至少500 positive和500 negative，
  Case-grouped且held-out Case贡献为0；
- 合同固定只允许 inner-validation fit、outer-held-out evaluate；
- 本阶段calibrator fit与threshold tuning均为0；
- 诊断层检查每seed是否存在同时满足
  recall=`1.0`、precision`>=0.80`、macro-F1`>=0.85`的单调阈值；
- 任一seed不存在可行阈值时，calibration-only路线不得GO。

### Gate 4：确定性与资源

- 正式Run A/B signature一致且Run B reference match=true；
- wall `<=10min`、CPU RAM `<=8GiB`、GPU VRAM=0；
- 未新增正式入口，未修改T01–T12。

## 6. 阶段决策

- 审计全部可信，表征和calibration-only路线均通过：
  `P05_SCHEME_A_P2_P3_P7_REPRESENTATION_GO_NEXT_TRAINING_REVIEW`
- 审计可信，但当前来源表征或calibration-only任一路线失败：
  `P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`
- 输入、hash、范围、确定性或审计自身失败：
  `P05_SCHEME_A_P2_P3_P7_AUDIT_NO_GO`

任何决策均不自动授权训练。若当前来源NO-GO，T03/T04推理角色提升或新增T06前
关系生成器必须由用户另行决策。
