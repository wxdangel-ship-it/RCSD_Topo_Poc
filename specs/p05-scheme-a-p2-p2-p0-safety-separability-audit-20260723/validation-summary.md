# P05-Scheme-A-P2-P2-P0 验证总结

## 1. 正式结论

本阶段已完成，正式判定为 **`P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`**。

该结论表示：P2-P1 的主要剩余问题已经定位到 Segment carrier 的安全接受，而不是候选缺失、Node carrier 来源或整图合法性。只重新设置 confidence、margin、entropy 或 anomaly 阈值无法在零错误前提下保留足够的正确 `USE_RCSD`；但现有完整 truth-free Segment feature 未发现跨 truth 精确碰撞，因此独立、Case-grouped、cross-fitted safety/abstention head 具备技术启动理由。

本阶段没有训练新模型，不改变 `P05_SCHEME_A_P2_P1_SAFETY_NO_GO`，也不授权 P2-P2-P1、在线 proposal 或生产接入。

## 2. 正式证据

- Audit Run A：`p05_scheme_a_p2_p2_p0_audit_20260723_01`
- Audit Run B：`p05_scheme_a_p2_p2_p0_audit_20260723_02`
- 两轮 `safety_signals`、`error_chains`、`review_audit`、feature collision、summary 和 report 内容 hash 全部一致。
- 输入为 P2-P1 dataset `20260723_01` 和 OOF `20260723_01/_02`；未重跑模型或修改原始 artifact。

## 3. 错误链结论

P2-P1 的 `17/9/17` 是“被标记 accepted 的 selected candidate 与原 truth candidate 不同”的对象级指标，不等于 43 个彼此独立的业务根错误。P2-P2-P0 将其全部归因后：

| seed | 原 accepted wrong | raw Segment 错误 | 真正 accepted Segment 根错误 |
|---:|---:|---:|---:|
| 17 | 17 | 12 | 2 |
| 29 | 9 | 10 | 0 |
| 43 | 17 | 37 | 3 |

5 条 accepted Segment 根错误来自 4 个唯一 Segment：

- `T10-Error-2:986209_996008_1 / 967135_607079526_1`：`MIXED_CARRIER -> KEEP_SWSD`，seed 17/43。
- `T10-Error:11836293_601393840 / 1067983_1071166`：`KEEP_SWSD -> USE_RCSD`，seed 17。
- `T10-Error-2:89387685_507565991 / 604053726_89387703`：`KEEP_SWSD -> USE_RCSD`，seed 43。
- `T10-Error-2:89387685_507565991 / 89387685_507565991`：`KEEP_SWSD -> USE_RCSD`，seed 43。

Node accepted-wrong 行中，20 条已由 effective structural fallback 改正，12 条由 accepted Segment 根错误传播，2 条来自 rejected Segment 的 fallback 前信号，4 条为独立或未引用 Node。49 个可发布 Case 的最终有效 Segment→Node requirement 没有 conflict 或 target mismatch；2 个 expected failure 继续单列、不发布。

因此不能把 `17/9/17` 直接解释为最终图上 43 个独立错误，也不能据此忽略仍真实存在的 `2/0/3` 个 Segment 根错误。P2-P1 NO-GO 仍成立，因为任何 seed 的错误自动替换门禁都要求为零。

## 4. 可分性结论

- 8 个 `KEEP_SWSD -> USE_RCSD` 错误在三个 seed 中完全稳定。
- 2,182 个 truth `USE_RCSD` 在三个 seed 中也均选为 `USE_RCSD`。
- 为排除全部 8 个 false-use，单一信号的最佳零错误覆盖为：
  - anomaly：`437/2182 = 0.200275`
  - margin：`346/2182 = 0.158570`
  - probability：`343/2182 = 0.157195`
  - entropy：`333/2182 = 0.152612`
- 最佳值 `0.200275 < 0.50`，所以 calibration-only 正式 NO-GO。
- 8,863 Segment 形成 8,510 个完整 feature signature，跨 truth 精确碰撞为 `0`。这只说明尚未证明现有特征不可分，不等价于 safety head 已经通过泛化验收。
- 40 个 Review 的自动发布数在三个 seed 均为 `0`；预测保持情况为 `40/40`、`40/40`、`12/40`，seed 43 的 28 个错误 `KEEP_SWSD` 仍完整保留。

## 5. 验证与治理

- 专项测试：`5 passed`，覆盖正常传播链、truth/坐标泄漏、artifact hash、缺失 seed/group 和 compatibility lineage。
- `py_compile` 通过。
- 正式审计双跑内容完全一致。
- P05 `src/` + `tests/` 共 `135` 个源码/测试文件，`>=60KiB=0`、`>=100KB=0`。
- 新审计实现 `36,487 bytes`，专项测试 `11,911 bytes`；全模块最大仍为 `scheme_a_baseline.py` 的 `58,135 bytes`。
- 未新增 CLI、`scripts/`、`__main__.py`、Makefile target 或 T10 stage，entrypoint registry 无变化。
- 当前 Windows Python 缺少 P05 optional `torch`；专项测试通过预加载轻量 P05 package namespace 避免导入未使用的历史神经模块。由于本阶段未修改既有 P05 文件，完整历史 P05 回归沿用 P2-P1 已通过的 158 项证据，本轮没有把未执行的完整回归表述为已执行。
- `docs/repository-metadata/path-conventions.md` 仍缺失；本工作树 `.venv` 是指向 `/mnt/e/Work/RCSD_Topo_Poc/.venv` 的 WSL reparse point，但该环境也未安装 `torch`。该项作为既有治理缺口保留。

## 6. 下一阶段技术方向

若用户另行授权 P2-P2-P1，应冻结 P2-P1 scorer，训练独立 Segment safety/abstention head，而不是改写 Road/Node scorer。输入可使用当前 truth-free candidate/context feature、multi-seed score统计、proposal/SWSD相对证据和 Junction条件化传播风险；训练与阈值必须嵌套 Case-grouped cross-fit，40 Review 保持禁止自动发布。目标仍是每 seed accepted wrong=`0`、precision=`1.0`、总体与 `USE_RCSD` safe coverage均`>=0.50`。
