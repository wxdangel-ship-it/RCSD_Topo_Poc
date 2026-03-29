# 025 Step2 Candidate Channel Architecture Split

## 日期
- 2026-03-29

## 背景
- `step2_segment_poc.py` 虽已回到 `100 KB` 阈值内，但 `candidate channel / segment-body-prep` 这组纯 helper 仍混在主文件里。
- 本轮用户要求继续做仅结构、不改业务结果的 Step2 治理。

## 本次边界
- 不修改 trunk gate、pair validation、segment_body retain 规则本身。
- 不修改 `run_step2_segment_poc`、`_validate_pair_candidates`、`_tighten_validated_segment_components` 的业务语义。
- 只抽离 candidate channel / prune / segment refine 子域，并补模块级文档记录。

## 实际变更
- 新增 `step2_candidate_channel_utils.py`，承接以下 5 个纯 helper：
  - `_build_candidate_channel`
  - `_build_segment_body_candidate_channel`
  - `_expand_segment_body_allowed_road_ids`
  - `_prune_candidate_channel`
  - `_refine_segment_roads`
- `step2_segment_poc.py` 改为直接 import 上述 helper，保留原有调用链与 monkeypatch 入口名，不改外部语义。
- `test_step2_candidate_channel_prune.py` 改为直接覆盖新模块入口。

## 结果
- Step2 子域边界进一步清晰：graph、runtime、support、candidate-channel 四组 helper 已拆离主文件。
- `step2_segment_poc.py` 继续收缩，只保留 validation / tighten / arbitration / CLI runner 主链。

## 验证要求
- 必须重跑 Step2 / Skill / CLI / freeze-compare 相关 pytest。
- 必须重跑 `XXXS1-8 no-debug + freeze compare`，确认 active baseline 不漂移。
