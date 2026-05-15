# Implementation Plan: P01 四 Case 收口与字段语义裁定

**Branch**: `p01-four-case-closure-and-field-semantics`
**Date**: 2026-05-15
**Spec**: `specs/p01-four-case-closure-and-field-semantics/spec.md`
**Status**: Ready for tasks（plan 已起草；tasks.md 起草后用户签收再进 implement）

---

## Summary

按用户裁决（C-1=A / C-2=D / C-3=α / 业务根因接受），对 P01 模块做四类**最小必要**修正：

1. **文档级**：契约 / architecture / risk / coverage_audit 四份模块文档的措辞精确化（baseroadid / kind / turntype）。
2. **代码级（极小）**：`topology.py` 输出 `junction_context.json` 时增加 `kind_distribution` audit 字段；不改变任何 trace / through / Arm / Movement / final generation 主规则。
3. **测试级**：新增 `tests/modules/p01_arm_build/test_p01_kind_audit.py` 覆盖 kind audit 字段（不追加到 96.7 KB 的 `test_p01_arm_build.py`）。
4. **基线级**：重跑 7 case e2e，建立 `modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/` observed baseline。

**显式不做**：

- 不改 P01-Final 业务判定主路径（不动 `final_road_next_road.py`）。
- 不改 turntype 编码值。
- 不修复 5659051 / 612654679 的"未达预期"现象（已锁定根因为上游 SWSD 数据缺失，可接受）。
- 不拆分逼近 100 KB 的源码文件（独立 SpecKit 任务）。
- 不升级任何 case 的 baseline 至 accepted。

---

## Technical Context

| 项 | 值 |
|---|---|
| Language / Version | Python 3.10+（仓库 `pyproject.toml` 既定） |
| Primary Dependencies | `fiona`、`shapely`（已在 `.venv` 中安装） |
| Storage | GPKG / JSON / GeoJSON / CSV（与既有 P01 输出一致） |
| Testing | `pytest`（既有约定） |
| Target Platform | WSL Ubuntu 上的 `.venv/bin/python`；本地 PowerShell 不具备运行 P01 runner 的依赖 |
| Project Type | Single-module modification within `modules/p01_arm_build/` |
| Performance Goals | NFR-005：与 6-case audit 总耗时偏差 ≤ ±30%（约 30–45 秒 / case） |
| Constraints | `AGENTS.md` §3 文件 100 KB 硬阈值；§5 GIS / 拓扑五项检查 |
| Scale / Scope | 7 个 case（中心路口节点 2–12 / seed 道路 8–15 / 几百~千条 RoadNextRoad） |

---

## Constitution Check（对照 `AGENTS.md` 项目级硬约束）

| 条款 | 自检 | 状态 |
|---|---|---|
| §1.1 源事实冲突 | 无新冲突；R1 已澄清为文档措辞精确化 | ✅ 通过 |
| §1.2 任务书授权 | 本任务书已锁定，授权修订 `INTERFACE_CONTRACT.md` 的 baseroadid / turntype 段与 `architecture/04 / 11` 的对应段 | ✅ 通过 |
| §1.3 入口治理 | 不新增任何官方执行入口；callable runner 签名不变 | ✅ 通过 |
| §1.4 文件体量 | `topology.py` 78 KB → +200 bytes（仅添加 audit 字段计数代码）→ 仍 < 100 KB；不追加到 `test_p01_arm_build.py` (96.7 KB)，新建 `test_p01_kind_audit.py` | ✅ 通过 |
| §1.5 字段反推 | 所有字段语义裁决都来自用户显式授权，不据局部样本固化 | ✅ 通过 |
| §1.6 路径环境 | implement 阶段 Phase C 要切换到 WSL；PowerShell 本会话只能完成 Phase A / B / D 中的文档与代码部分 | ⚠️ 需用户在 Phase C 切 WSL |
| §1.7 入口变更 | 非入口变更任务 | ✅ 通过 |
| §3 体量自检 | 每个写入文件前必须 `Get-ChildItem` 字节数 | ✅ 计划遵守 |
| §5 GIS / 拓扑 | CRS / 拓扑一致性 / 几何语义 / 审计可追溯 / 性能可验证 全部覆盖 | ✅ 通过 |
| §6 五视角覆盖 | 见下 | ✅ 通过 |

### 五视角覆盖

- **产品**：明确"P01 模块在 7 case 上的业务诉求满足度判定"由字段语义裁定 + observed baseline + 根因说明三者共同支撑；5659051 / 612654679 未达预期被显式归类为上游数据问题。
- **架构**：无新接口、无新构建块；`junction_context.json` 增加可选 audit 字段，对 A2 / Final 兼容（A2 / Final 不消费该字段）。
- **研发**：四阶段任务（Phase A / B / C / D），每阶段都有可验证产物；Phase A / B / D 在 PowerShell 完成；Phase C 必须切 WSL。
- **测试**：Phase B 完成时新增 `test_p01_kind_audit.py`；Phase D 完成后必须验证 3 个 accepted case 与既有 2026-05-12 baseline 哈希一致（SC-005 无回归）。
- **QA**：Phase D 完成时必须断言：(a) baseline manifest 的输入 checksum 与原始 `manifest.json` checksum 一致；(b) `frcsd_road_next_road.geojson` 无重复 `(road_id, next_road_id)` 对；(c) 输出 GeoJSON 的 CRS 与输入 F-RCSD `roads.gpkg` 一致（WGS 84）。

---

## Project Structure

### Documentation (this feature)

```text
specs/p01-four-case-closure-and-field-semantics/
├── plan.md              # 本文件
├── spec.md              # 已锁定（C-1/C-2/C-3 等已裁决）
├── tasks.md             # 下一步起草
├── research.md          # 已用 outputs/_work/p01_audit_2026-05-15/*.md 替代，不再单独出
└── data-model.md        # N/A（本任务不引入新字段实体）
```

### Files Touched

```text
# Phase A 修订（文档）
modules/p01_arm_build/INTERFACE_CONTRACT.md         # §3.1 / §8 baseroadid 精确化；§8 turntype 加 NEEDS_CLARIFICATION
modules/p01_arm_build/architecture/02-constraints.md         # baseroadid 表述对齐
modules/p01_arm_build/architecture/04-solution-strategy.md   # 增加未列举 kind 兜底声明
modules/p01_arm_build/architecture/11-risks-and-technical-debt.md  # baseroadid 风险条目精确化
modules/p01_arm_build/history/p01_v1_coverage_audit.md       # 追加字段语义裁定行 + 业务根因记录

# Phase A 修订（审计报告）
outputs/_work/p01_audit_2026-05-15/P01_audit_report.md       # R1 评级降级
outputs/_work/p01_audit_2026-05-15/P01_business_correctness_report.md  # 已存在；本任务不改

# Phase B 代码改动
src/rcsd_topo_poc/modules/p01_arm_build/topology.py          # 仅 junction_context.json 增 kind_distribution 字段；不动业务规则
tests/modules/p01_arm_build/test_p01_kind_audit.py           # 新增单元测试
docs/repository-metadata/code-size-audit.md                  # 更新 topology.py 与 test_p01_arm_build.py 体量记录

# Phase C 执行（必须 WSL）
outputs/_work/p01_seven_cases_baseline_observed_20260515/    # 新 run root（具体路径由 implement 阶段命令决定）

# Phase D 基线落档
modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/
├── README.md
├── manifest.json
├── case_summary.csv
├── final_pass_relations_with_original_evidence.csv
└── cases/<case_id>/
    ├── frcsd_road_next_road.geojson
    ├── frcsd_road_next_road_audit.json
    ├── frcsd_road_next_road_issue_report.json
    ├── final_generation_decisions.json
    └── preflight.json
```

**Structure Decision**：本任务**不引入新目录、不动模块边界**。所有修订都落在 P01 模块内部既有文档 / 实现 / 测试 / baseline 目录中。

---

## Phasing

### Phase A：文档修订（可在 PowerShell 完成，零运行时风险）

1. 体量自检每个目标文件（确认在硬阈值下）。
2. 用 StrReplace 做最小局部修订；每次只动一处。
3. ReadLints 验证。

### Phase B：代码最小改动（可在 PowerShell 完成；不触发运行时）

1. 体量自检 `topology.py`：当前 78053 bytes。
2. 找到 `junction_context.json` 的构造点（推测在 `build_dataset_arm_result` 或相邻位置），追加 `kind_distribution` 字段。
3. 新建 `test_p01_kind_audit.py`（**不**碰 96.7 KB 的 `test_p01_arm_build.py`）。
4. ReadLints 验证；不在本会话运行 pytest（无 fiona）。
5. 更新 `docs/repository-metadata/code-size-audit.md` 记录 topology.py 新体量。

### Phase C：7 case e2e 重跑（**必须切 WSL**）

打包成一份独立 bash 命令清单（Phase C kit）交给用户在 WSL 中执行，内容包括：

- 调用 `dev_helpers/run_p01_case_full.sh` 或直接 `python -c "from ...runner import run_p01_arm_build_from_args; ..."`
- 每个 case 用 `outputs/_work/p01_seven_cases_baseline_observed_20260515/<case_id>/` 作 run-root
- 收集 `preflight.json`、`p01_arm_build_summary.json` 等供 Phase D 引用

### Phase D：observed baseline 落档（可在 PowerShell 完成；只读 Phase C 输出 + 写 baseline 目录）

1. 从 Phase C 输出收集每 case 的 7 个核心文件。
2. 用 SHA-256 计算 manifest 各文件 checksum。
3. 生成 `manifest.json` / `case_summary.csv` / `final_pass_relations_with_original_evidence.csv` / `README.md`。
4. SC-005 回归校验：3 个 accepted case 的 `frcsd_road_next_road.geojson` 与 `baselines/p01_final_three_cases_accepted_2026-05-12/` 内对应文件做行级 diff，差异 = 0 才算 pass。
5. NFR-002 / NFR-003 / NFR-004 自动断言。

---

## Risks & Mitigations

| 风险 | 缓解 |
|---|---|
| Phase C 在 WSL 中重跑结果与现有 baseline 不一致（SC-005 fail） | 把 diff 内容输出为 issue；不强行 mask，提醒用户复核 |
| `topology.py` 修改无意中波及 trace / through 判定 | 修改严格只新增 audit 字段；通过新测试 + 既有 6-case e2e 验证 |
| `test_p01_arm_build.py` 被无意修改触发体量超限 | 本任务**禁止**改动该文件；所有新测试入新文件 |
| Phase C 用户在 WSL 跑出来的 run-root 与 PowerShell 看不到的路径不一致 | 在 Phase C kit 内写明 `outputs/_work/...` 相对路径，并在 Phase D 用 `wslpath` / 相对路径处理 |
| 修订 `INTERFACE_CONTRACT.md` 触发 §1.2 保护区 | 已在 spec §0 / §6 显式授权该文件的 baseroadid / turntype 段修订；按 default-imp 最小局部改动 |

---

## Complexity Tracking

无 Constitution Check 违规；不需要复杂性辩护。

---

## Exit Criteria

- spec.md 中 C-1 / C-2 / C-3 / C-4 / C-5 / C-6 / C-7 已全部锁定（done）
- tasks.md 起草完成（next step）
- 用户在 tasks.md 上签收 → implement Phase A → B → C → D
- 所有 Success Criteria SC-001 ~ SC-007 满足
