# P05-Scheme-A-Dataset-P0 实施计划

状态：已于 2026-07-22 完成。正式双跑、确定性、GIS/资源、完整 P05 回归与源事实同步均通过，结论 `P05_SCHEME_A_DATASET_P0_GO`。

## 1. 数据流

```text
M0 sample/artifact/split
  + M2R T03/T04/T05/T06 supervision
  + Scheme A frozen skeleton/carrier labels
  + truth-free PTO candidate
  + label-only PTO solve + historical P2 safety
  -> module role contract
  -> sample/artifact/task manifest
  -> T01 fallback vs non-T01 proposal source audit
  -> Segment Road + final Road/Node reachability
  -> Oracle/RoadGraph safety evidence join
  -> immutable Dataset-P0 run + second deterministic run
```

## 2. 文件设计

- `scheme_a_dataset_p0_models.py`：配置、阈值和稳定 schema。
- `scheme_a_dataset_p0.py`：输入验证、模块角色、标签/权重/mask、候选来源、Road/Node 可达性和 run 工件。
- `__init__.py`：导出 callable，不新增执行入口。
- `test_scheme_a_dataset_p0.py`：单元、隔离和破坏测试。

## 3. 实施步骤

1. 验证 M0、M2R、Scheme A baseline、PTO candidate/solve 与历史 P2 manifest/hash。
2. 建立九模块稳定训练角色合同，并固定 T07 `DRIVEZONE_ONLY`。
3. 输出 741 sample、M0 artifact 和 M2R target 的语义化清单。
4. 流式读取 PTO candidate，按 T01 fallback、raw RCSD、T03-T06 strategy proposal 分类。
5. 以 Scheme A Segment label 为分母，独立计算全体和 `USE_RCSD` Road candidate reachability。
6. 读取 T06 final Road/Node GPKG 对象 ID，验证全图对象可达性和 CRS。
7. 连接 PTO semantic exact 与 Scheme-A-P2 49+2 safety 证据，形成最终 Gate。
8. 执行 Run A/B、测试、确定性、资源、体量和入口治理审计。
9. 写入 validation summary，并同步 P05 项目级/模块级 source-of-truth。

## 4. 验证顺序

1. SpecKit 五职责和源事实一致性。
2. 配置、角色、mask、hash 与候选来源单元测试。
3. 真实冻结数据 Run A/B。
4. Road/Node reachability、49+2 safety、CRS/GIS和资源检查。
5. 完整 P05 回归、源码体量与入口治理检查。

## 5. 非目标

- 不训练 scorer。
- 不处理 Movement。
- 不修改 T01-T12、T10 或生产主链。
- 不新增 Case、入口、业务强规则或 truth-derived candidate。
