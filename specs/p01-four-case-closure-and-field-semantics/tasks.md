# Tasks: P01 四 Case 收口与字段语义裁定

**Branch**: `p01-four-case-closure-and-field-semantics`
**Date**: 2026-05-15
**Status**: Ready for implement（任务列表已起草，等待执行）
**Reference**: `spec.md` §3 / `plan.md` §Phasing

---

## 任务编号约定

- `T-A.*`：Phase A 文档修订
- `T-B.*`：Phase B 代码最小改动 + 新测试
- `T-C.*`：Phase C 7 case e2e 重跑（**WSL only**）
- `T-D.*`：Phase D observed baseline 落档
- `T-Q.*`：Phase Q 收尾审计与回归校验

依赖图：

```text
T-A.* (独立)  T-B.* (独立)
        ↓        ↓
       T-Q.A (lint + 文档一致性)
                 ↓
              T-C.*  (实际 e2e)
                 ↓
              T-D.*  (basinele build)
                 ↓
              T-Q.D  (SC-001 ~ SC-007 校验)
```

---

## Phase A：文档修订（可在 PowerShell 完成）

### T-A.1：精确化 `INTERFACE_CONTRACT.md` §3.1 / §8 中 `baseroadid` 描述
- 体量自检 → StrReplace
- 把"`baseroadid` 在已验证 case 中为空，不作为来源映射依据"改为：
  > `baseroadid` 字段在 7 个本地验证 case（1019789 / 38724646 / 5312848 / 5595587 / 5659051 / 612654679 / 950044）的 F-RCSD `roads.gpkg` 中实测为 JSON 空数组的字符串字面值 `"[]"`。其设计意图为多源 base road id 合并链路审计字段；当前 F-RCSD 数据未填充。**不**作为来源映射依据，映射仍走 `Source + CRS 归一化 rounded exact geometry`。
- 验收：`Grep "baseroadid"` 在该文件不再出现旧措辞，新措辞唯一。

### T-A.2：在 `INTERFACE_CONTRACT.md` §8 turntype 映射段后追加 `NEEDS_CLARIFICATION_FROM_RCSD_SPEC`
- 体量自检 → StrReplace
- 在现行 `unknown -> 0 / straight -> 1 / left -> 2 / right -> 3 / uturn -> 4` 表下追加说明：
  > **注**：以上映射是仓库内部审计编码，**无外部 RCSD 规范权威依据**。标 `NEEDS_CLARIFICATION_FROM_RCSD_SPEC`。在权威 RCSD 编码规范确认前，下游消费方**不得**对该字段做强语义解释；未来取得规范后，需独立 SpecKit 任务修订本段、`final_road_next_road.py` 映射逻辑与既有 baseline 全量回归。
- 验收：grep `NEEDS_CLARIFICATION_FROM_RCSD_SPEC` 找到一次。

### T-A.3：精确化 `architecture/11-risks-and-technical-debt.md` 中 `baseroadid` 段
- 体量自检 → StrReplace
- 替换"`baseroadid` 在验证 case 中为空"为与 T-A.1 同口径的精确描述。
- 验收：与 T-A.1 同步。

### T-A.4：精确化 `architecture/02-constraints.md` 中 baseroadid 段
- 体量自检 → StrReplace
- 与 T-A.1 同口径。
- 验收：与 T-A.1 同步。

### T-A.5：在 `architecture/04-solution-strategy.md` Trace 节追加"未列举 kind 兜底"声明
- 体量自检 → StrReplace
- 在 Trace 章节末尾新增段落（约 5 行）：
  > **未列举 kind 值的兜底语义**：实测 7 case 中出现的 `kind` 值包括独立位 {1, 4, 8, 16, 2048, 8192} 与复合值 {12 = 4|8, 20 = 4|16}。其中 bit2 (kind=4) 维持既有边界候选规则；bit11 (kind=2048) 维持既有 T 型规则；其它独立位与复合值（除非 bit2 命中）按 `kind != 4` 默认 continue trace 兜底。`junction_context.json` 必须输出当前 case 的 `kind_distribution` audit 字段，便于后续上游字段语义裁定。
- 验收：grep `未列举 kind` 找到一次。

### T-A.6：在 `history/p01_v1_coverage_audit.md` 追加字段语义裁定行 + 业务根因记录
- 体量自检 → StrReplace
- 在表的末尾追加 3 行：
  | 28 | baseroadid 字段语义 | 已裁定（2026-05-15） | 字符串空数组 `"[]"`，不作来源映射；契约措辞已精确化 |
  | 29 | 未列举 kind 兜底 | 已裁定（2026-05-15） | `kind != 4` 默认 continue；junction_context.json 加 kind_distribution audit |
  | 30 | turntype 编码权威性 | 标 NEEDS_CLARIFICATION_FROM_RCSD_SPEC | 不改编码值；下游不得强解释 |
- 在末尾"未完全闭合项"段补一句：
  > 5659051 / 612654679 / 5312848 / 5595587 在 P01 v1.0.0 范围内未升级 accepted；根因为上游 SWSD RoadNextRoad 数据稀疏或完全缺失（5659051 / 612654679 在中心路口 SWSD RoadNextRoad = 0 条），仓库实现合规走 alternate / corridor ordinal projection；observed baseline 已落档 `baselines/p01_final_seven_cases_observed_2026-05-15/`。
- 验收：grep 三条新行各一次。

---

## Phase Q.A：Phase A 收尾

### T-Q.A.1：ReadLints 全部 Phase A 文件
- 对 T-A.1 ~ T-A.6 修订过的 6 个文件执行 ReadLints；任何 markdown / typography 错误必须 0 起步。

### T-Q.A.2：契约 / architecture / coverage_audit 三方一致性扫描
- `Grep "baseroadid"` 跨 `modules/p01_arm_build/**/*.md`，确保所有出现处口径一致。
- `Grep "turntype"` 跨同范围，确保新增 NEEDS_CLARIFICATION_FROM_RCSD_SPEC 仅在契约 §8 出现一次（其它处不重复声明）。

---

## Phase B：代码最小改动（PowerShell + ReadLints；不运行 pytest）

### T-B.1：定位 `junction_context.json` 构造点
- 在 `src/rcsd_topo_poc/modules/p01_arm_build/topology.py` Grep `junction_context` 与 `JunctionContext`，找到 dataclass 构造与 JSON 序列化的位置。
- 不读其它无关函数；只读相关 ±50 行。

### T-B.2：在 `JunctionContext` dataclass 中追加 `kind_distribution: dict[int, int] = field(default_factory=dict)` 字段
- 体量自检：当前 78053 bytes；预计 +200 ~ +400 bytes，结束后 ≤ 79 KB，远低于 100 KB。
- 字段语义：从 member nodes 收集 `kind` 值的 Counter，以 `{<kind_value_as_int>: <count>}` 形式输出。
- 不改 Arm / trace / through / Movement 任何主规则。
- 不改 `models.py` 公共导出（如果 JunctionContext 在 `models.py` 而非 `topology.py`，需相应调整目标文件；按 Grep 结果调整 T-B.2 / T-B.3 文件路径）。

### T-B.3：在 dataset 处理函数末尾构造 `kind_distribution` 并写入 JunctionContext
- 找到现有 `member_node_ids` / `kind` 访问点；用一次性 `Counter` 计算分布；不引入新数据结构。

### T-B.4：体量自检 `topology.py` 修改后大小并更新 `docs/repository-metadata/code-size-audit.md`
- 用 `Get-ChildItem` 检查实际字节数。
- 在 `code-size-audit.md` 对应行更新 "current size" 字段，若该表已经登记此文件；如未登记，本任务**不**新增（避免范围扩张）。

### T-B.5：新建 `tests/modules/p01_arm_build/test_p01_kind_audit.py`
- 写一个最小测试：构造一个 in-memory `JunctionContext`，验证 `kind_distribution` 字段存在、序列化进 JSON、内容正确。
- **禁止追加到 `test_p01_arm_build.py`**（已 96.7 KB）。
- 测试预计 50-80 行。

### T-B.6：ReadLints 验证 Phase B 文件
- 对 `topology.py` 和新增测试文件做 lint 检查。

---

## Phase Q.B：Phase B 收尾

### T-Q.B.1：源码字段 / 测试一致性扫描
- 在 `topology.py` Grep `kind_distribution` 应有 2-3 次出现（dataclass + 构造 + 序列化），数量级合理。
- 测试文件中 import 路径与既有测试一致。

### T-Q.B.2：本会话不运行 pytest，但准备 Phase C kit 时附 `pytest tests/modules/p01_arm_build/test_p01_kind_audit.py -v` 作为 WSL 内执行项。

---

## Phase A→B 完成后：用户验收门（建议）

> Phase A + B 完成后建议用户在执行 Phase C 前 review，确保文档措辞 / 代码改动符合预期。本任务书在 Phase B 完成时回报"待用户确认进入 Phase C"。

---

## Phase C：7 case e2e 重跑（WSL）

**前置**：Phase A / B 完成；本任务在 PowerShell 中**不能**执行 Phase C。打包为 Phase C kit 交用户。

### T-C.0：打包 Phase C kit
- 在 `outputs/_work/p01_audit_2026-05-15/phase_c_kit/` 输出一份 `run_phase_c.sh` 与 `README.md`。
- 命令形态：
  ```bash
  for case in 1019789 38724646 5312848 5595587 5659051 612654679 950044; do
    bash modules/p01_arm_build/dev_helpers/run_p01_case_full.sh \
      CASE_ROOT=/mnt/e/TestData/POC_Data/Interestion/$case \
      OUT_ROOT=outputs/_work/p01_seven_cases_baseline_observed_20260515 \
      RUN_ID=case_${case}_baseline_observed
  done
  ```
- kit 内附验证命令：每 case 生成完后 `ls cases/group_0001/FRCSD/frcsd_road_next_road.geojson` 不空。
- Phase C 不在 implement 阶段由本任务自动触发；由用户在 WSL 执行。
- 用户执行完 Phase C 后，需要在本任务回报 run-root 完整路径，本任务才进 Phase D。

---

## Phase D：observed baseline 落档（PowerShell；只读 Phase C 输出）

**前置**：用户已完成 Phase C 并提供 run-root 路径。

### T-D.1：建立目录骨架
- `New-Item -ItemType Directory -Force` 建立：
  - `modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/`
  - 同目录下 `cases/<case_id>/` 7 个子目录

### T-D.2：复制 / 收集 7 case 核心文件到 baseline
- 每 case 复制：
  - `frcsd_road_next_road.geojson`
  - `frcsd_road_next_road_audit.json`
  - `frcsd_road_next_road_issue_report.json`
  - `final_generation_decisions.json`
  - `preflight.json`

### T-D.3：计算每个 baseline 文件的 SHA-256，并对照原始 `manifest.json` 中的输入 checksum
- 写 `manifest.json` 顶层字段：
  - `accepted_status`: `"observed_not_accepted"`
  - `created_at`: `2026-05-15...`
  - `source_run_root`: `<phase C run-root>`
  - `tool_versions`: `python --version`、`.venv` site-packages summary（关键依赖 fiona / shapely / pyproj）
  - `case_index`: 7 case 各项 checksum + 行数 + 输入 checksum
  - `note`: "本 baseline 为 observed 状态，不等价于 accepted。详见 README.md"

### T-D.4：生成 `case_summary.csv`
- 字段：`case_id, accepted_status, generated_count, manual_review_required_count, alternate_source_projected_count, partial_target_count, failed_group_count, p0_count, p1_count, root_cause_note`
- `root_cause_note` 从 `P01_business_correctness_report.md` §3.2 直接引用对应 case 句子。

### T-D.5：生成 `final_pass_relations_with_original_evidence.csv`
- 与既有 `baselines/p01_final_three_cases_accepted_2026-05-12/` 同 schema。
- 7 case 合并；列：`case_id, f_road_id, f_next_road_id, type, source, turntype, city_code, primary_source, rule_status, generation_rule, confidence, source_evidence_ids`。

### T-D.6：生成 `README.md`
- 顶部说明本 baseline 是 observed_not_accepted 状态。
- 列出每个 case 的 accepted_status + 根因引用：
  - 3 个已 accepted case（1019789 / 38724646 / 950044）：与 2026-05-12 baseline 等价（哈希一致），仅作 7 case 完整性保留。
  - 5312848：SWSD 中心路口 RoadNextRoad 仅 2 条；仓库 31 条规则主要来自 RCSD + alternate projection；合规放大。
  - 5595587：SWSD 1 条；仓库 19 条与 RCSD 20 条对齐。
  - 5659051：**SWSD 0 条**；仓库 13 条全部走 alternate projection；非 P01 实现缺陷，归 SWSD 上游数据治理。
  - 612654679：**SWSD 0 条**；仓库 13 条全部走 alternate projection；同 5659051。
- 标"后续 accepted 升级路径"：业务侧接受 alternate projection / SWSD 上游数据补齐后重跑。

---

## Phase Q.D：Phase D 收尾与 Success Criteria 校验

### T-Q.D.1：SC-001 验证（R1 closed）
- Grep `baseroadid` 跨 `modules/p01_arm_build/`，确保 contract / architecture / coverage_audit 三处描述一致。

### T-Q.D.2：SC-002 验证（baseline 完整性）
- `Get-ChildItem` baseline 目录树，断言每 case 5 个核心文件均存在，manifest 引用一致。

### T-Q.D.3：SC-003 验证（kind 兜底显式声明）
- Grep `未列举 kind` 在 `architecture/04-solution-strategy.md` 找到一次；`kind_distribution` 在 `topology.py` 与新测试文件中出现合理次数。

### T-Q.D.4：SC-004 验证（turntype 非权威标注）
- Grep `NEEDS_CLARIFICATION_FROM_RCSD_SPEC` 在 `INTERFACE_CONTRACT.md` 找到一次。

### T-Q.D.5：SC-005 验证（**无回归**）
- 对 1019789 / 38724646 / 950044 三个 accepted case，diff Phase C 生成的 `frcsd_road_next_road.geojson` 与 `baselines/p01_final_three_cases_accepted_2026-05-12/cases/<case>/frcsd_road_next_road.geojson`：行级 diff 应该为 0；若非 0 进入 P0 issue，不允许 mask。

### T-Q.D.6：SC-006 验证（治理同步）
- 检查 `docs/repository-metadata/code-size-audit.md` 中 `topology.py` 行的 size 与实际字节数一致。

### T-Q.D.7：SC-007 验证（可复现）
- 用 manifest 中记录的 input checksum 与 `E:\TestData\POC_Data\Interestion\<case>\manifest.json` 中 checksum 比对；100% 一致才算 pass。

### T-Q.D.8：NFR-002 / NFR-003 / NFR-004 自动断言
- NFR-002：每个 baseline `frcsd_road_next_road.geojson` 内 `(road_id, next_road_id)` 对去重后等于总 feature 数（无重复）。
- NFR-003：每 case 输入 checksum 与原始 manifest 一致（与 SC-007 重合）。
- NFR-004：抽样 20 条 final pass relation，能在 `final_generation_decisions.json` / `frcsd_road_next_road_audit.json` 内找到对应 decision 行。

---

## Phase Z：审计报告同步

### T-Z.1：更新 `outputs/_work/p01_audit_2026-05-15/P01_audit_report.md`
- 在 §5.R1 段标记：
  > **2026-05-15 更正**：R1 在后续 baseroadid 全字段 distinct value 量化复核后判定为**审计误报**。字段实测为 JSON 空数组的字符串字面值 `"[]"`，业务语义即"空"，与既有契约陈述一致。本条降为"已澄清-文档措辞精确化"。
- 在 §6.1 末尾追加"R1 已撤销"。
- 不修订其它结论。

### T-Z.2：在 `outputs/_work/p01_audit_2026-05-15/` 添加 `phase_completion_log.md`
- 写每个 phase 完成时的关键 metric（实际字节数、运行耗时、输出文件 checksum 等），作为 implement 阶段过程审计证据。

---

## 验收清单（一行回报模板）

```
T-A.1 done | T-A.2 done | T-A.3 done | T-A.4 done | T-A.5 done | T-A.6 done
T-Q.A.1 done | T-Q.A.2 done
T-B.1 done | T-B.2 done | T-B.3 done | T-B.4 done | T-B.5 done | T-B.6 done
T-Q.B.1 done | T-Q.B.2 done
=== 用户在 Phase A+B 完成后 review ===
T-C.0 kit ready  → 用户在 WSL 执行 → 回报 run-root
=== Phase D 启动 ===
T-D.1..6 done
T-Q.D.1..8 done
T-Z.1..2 done
=== 验收完成 ===
```
