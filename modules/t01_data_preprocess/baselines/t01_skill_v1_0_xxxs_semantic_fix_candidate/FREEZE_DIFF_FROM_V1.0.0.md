# T01 Skill v1.0.0 Semantic Fix Candidate Diff

- baseline: `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- candidate: `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs_semantic_fix_candidate/`
- compare status: `FAIL`

## validated_pairs
- status: `FAIL`
- current_count: `46`
- baseline_count: `42`
- only_in_current_sample: `[{"a_node_id": "40237137", "b_node_id": "55225270", "left_turn_excluded_mode": "strict", "pair_id": "STEP4:40237137__55225270", "residual_road_count": "0", "segment_body_road_count": "2", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "40237164", "b_node_id": "74463926", "left_turn_excluded_mode": "strict", "pair_id": "STEP5B:40237164__74463926", "residual_road_count": "0", "segment_body_road_count": "1", "stage": "STEP5", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "763111", "b_node_id": "768595", "left_turn_excluded_mode": "strict", "pair_id": "S2:763111__768595", "residual_road_count": "1", "segment_body_road_count": "4", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "767010", "b_node_id": "26755593", "left_turn_excluded_mode": "strict", "pair_id": "STEP4:767010__26755593", "residual_road_count": "0", "segment_body_road_count": "1", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "767738", "b_node_id": "768622", "left_turn_excluded_mode": "strict", "pair_id": "S2:767738__768622", "residual_road_count": "5", "segment_body_road_count": "10", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "768639", "b_node_id": "12823253", "left_turn_excluded_mode": "strict", "pair_id": "S2:768639__12823253", "residual_road_count": "1", "segment_body_road_count": "12", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "787129", "b_node_id": "55225228", "left_turn_excluded_mode": "strict", "pair_id": "STEP4:787129__55225228", "residual_road_count": "0", "segment_body_road_count": "1", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}]`
- only_in_baseline_sample: `[{"a_node_id": "763111", "b_node_id": "768595", "left_turn_excluded_mode": "strict", "pair_id": "S2:763111__768595", "residual_road_count": "0", "segment_body_road_count": "5", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "767738", "b_node_id": "768622", "left_turn_excluded_mode": "strict", "pair_id": "S2:767738__768622", "residual_road_count": "2", "segment_body_road_count": "13", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"a_node_id": "768639", "b_node_id": "12823253", "left_turn_excluded_mode": "strict", "pair_id": "S2:768639__12823253", "residual_road_count": "0", "segment_body_road_count": "13", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}]`

## segment_body_membership
- status: `FAIL`
- current_count: `153`
- baseline_count: `153`
- only_in_current_sample: `[{"layer_role": "segment_body", "pair_id": "STEP4:40237137__55225270", "road_id": "46336763", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "STEP4:40237137__55225270", "road_id": "616663182", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "STEP4:767010__26755593", "road_id": "611943778", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "STEP4:787129__55225228", "road_id": "510365722", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "STEP5B:40237164__74463926", "road_id": "502148533", "stage": "STEP5B", "trunk_mode": "counterclockwise_loop"}]`
- only_in_baseline_sample: `[{"layer_role": "segment_body", "pair_id": "S2:763111__768595", "road_id": "510365722", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "S2:767738__768622", "road_id": "46336763", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "S2:767738__768622", "road_id": "502148533", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "S2:767738__768622", "road_id": "616663182", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "segment_body", "pair_id": "S2:768639__12823253", "road_id": "611943778", "stage": "Step2", "trunk_mode": "counterclockwise_loop"}]`

## trunk_membership
- status: `FAIL`
- current_count: `153`
- baseline_count: `148`
- only_in_current_sample: `[{"layer_role": "trunk", "pair_id": "STEP4:40237137__55225270", "road_id": "46336763", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "trunk", "pair_id": "STEP4:40237137__55225270", "road_id": "616663182", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "trunk", "pair_id": "STEP4:767010__26755593", "road_id": "611943778", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "trunk", "pair_id": "STEP4:787129__55225228", "road_id": "510365722", "stage": "Step4", "trunk_mode": "counterclockwise_loop"}, {"layer_role": "trunk", "pair_id": "STEP5B:40237164__74463926", "road_id": "502148533", "stage": "STEP5B", "trunk_mode": "counterclockwise_loop"}]`
- only_in_baseline_sample: `[]`

## refreshed_nodes_hash
- status: `FAIL`
- current_sha256: `ca1a921e14d4db0902fc4a069e7fd0b7fc076fe391dcdceca2fbb6c4bd60b46e`
- baseline_sha256: `6fc960b0245268a843a558418a52ca24d4cdde058e0d9148443efe953136386a`

## refreshed_roads_hash
- status: `FAIL`
- current_sha256: `71492f67e46732a33b66a30ed7145ab1d6dc43859c360a16106e12cc592389d7`
- baseline_sha256: `ed04ded3116b31a809510f6029dc11f363914c41b81f654fca334694da4df687`
