# P05 方案 A 数据模型

## FrozenSchemeACase

- `case_key/family/business_id/sample_id/fold`
- `crs`
- `source_manifest/source_hashes`
- `skeleton_signature`
- `junctions[]`
- `segments[]`
- `junction_segment_relations[]`
- `physical_movements[]`
- `content_repair=false`
- `silent_fix=false`

## FrozenSegment

- `segment_id`
- `segment_type`: `STANDARD | ADVANCE_RIGHT`
- `pair_nodes[]`
- `junc_nodes[]`
- `swsd_road_ids[1..n]`
- `direction_structure`
- `independent_road_valid`
- `source_segment_access/target_segment_access`：仅 `ADVANCE_RIGHT` 必填
- `access_valid`
- `evidence_refs[]`

## FrozenPhysicalMovement

- `movement_id/junction_id`
- `from_segment_access/to_segment_access`
- `carrier_kind`: `NODE | ROAD | UNKNOWN`
- `carrier_ids[]`
- `carrier_exclusive`
- `affects_shared_junction_unit`
- `evidence_refs[]`

## StrategyBaselineRecord

- `case_key/segment_id`
- `relation_status/relation_reason/source_mix`
- `outcome`: `SUCCESS_DIRECT | SUCCESS_WITH_FALLBACK | FAIL`
- `carrier_target`: `USE_RCSD | KEEP_SWSD | MIXED_CARRIER | REVIEW_FALLBACK`
- `selected_road_ids[]`
- `swsd_fallback_road_ids[]`
- `lineage`

## CarrierLabel

- `case_key/object_type/object_id`
- `skeleton_signature`
- `carrier_target`: Segment 为 `USE_RCSD | KEEP_SWSD | MIXED_CARRIER | REVIEW_FALLBACK`；Movement 为 `USE_RCSD | REVIEW_FALLBACK`
- `target_kind/target_payload`
- `label_weight/weight_role/fold`
- `available/mask_reason`
- `label_only=true`
- `feature_uses_truth=false`

## RealityChangeClue

- `clue_id/case_key`
- `scope`: `SEGMENT | JUNCTION | MOVEMENT`
- `object_id/code/detail`
- `evidence_refs[]`
- `recommended_fallback`
- `status=OPEN`
- `skeleton_mutation=false`

## FallbackPlan

- `trigger/clue_ids[]`
- `unit`: `MOVEMENT | SEGMENT | JUNCTION`
- `junction_ids[]/segment_ids[]/movement_ids[]`
- `retained_swsd_road_ids[]`
- `outcome`
- `failure_reasons[]`
- `skeleton_mutation=false`
