# T08 Preprocess Tasks

## Phase 0 - Redefinition Only

- [x] Product: define T08 as project base data preprocessing module.
- [x] Architecture: split T08 from T00 and keep first round callable-only.
- [x] Development: freeze Road Phase 1 migration shape without writing implementation.
- [x] Testing: define synthetic vector test requirements.
- [x] QA: define CRS / topology / geometry semantics / audit / performance closeout checks.

## Phase 1 - Contract And Docs

- [x] Create `modules/t08_preprocess/AGENTS.md`.
- [x] Create `modules/t08_preprocess/INTERFACE_CONTRACT.md`.
- [x] Create required architecture docs for Tool1 / Tool2 / Tool3.
- [x] Keep Tool3 以外的 Node preprocessing deferred in the contract.
- [x] Revise docs for Tool3 Nodes type aggregation and keep other Node preprocessing deferred.

## Phase 2 - Tool Implementation

- [x] Before each `.py` write, record current file byte size.
- [x] Create `src/rcsd_topo_poc/modules/t08_preprocess/__init__.py`.
- [x] Implement Tool1 SHP / GeoJSON to GPKG and GPKG to GeoJSON conversion.
- [x] Implement Tool2 Road PatchID join.
- [x] Implement Tool2 Road Kind enrichment.
- [x] Implement Tool2 combined callable runner and artifact dataclass.
- [x] Implement Tool3 Nodes type aggregation.
- [x] Add `scripts/t08_tool1_shp_to_gpkg.py`.
- [x] Add `scripts/t08_tool2_road_preprocess.py`.
- [x] Add `scripts/t08_tool3_nodes_type_aggregation.py`.
- [x] Register T08 scripts in `docs/repository-metadata/entrypoint-registry.md`.

## Phase 3 - Tests

- [x] Add focused synthetic tests under `tests/modules/t08_preprocess/`.
- [x] Cover Tool1 same-directory SHP / GeoJSON to GPKG and GPKG to GeoJSON output.
- [x] Cover Tool2 GPKG-only inputs.
- [x] Cover Tool2 `EPSG:3857` output CRS.
- [x] Cover Tool3 `EPSG:3857` output CRS.
- [x] Cover script parameterized paths.
- [x] Cover Tool2 `patch_id`, unmatched audit, and `kind`.
- [x] Cover Tool3 `kind_2 / grade_2 / mainnodeid` aggregation for roundabout and complex div/merge.

## Phase 4 - QA And Closeout

- [x] Run `.venv/bin/python -m pytest tests/modules/t08_preprocess`.
- [x] Run `.venv/bin/python scripts/t08_tool1_shp_to_gpkg.py --help`.
- [x] Run `.venv/bin/python scripts/t08_tool2_road_preprocess.py --help`.
- [x] Run `.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py --help`.
- [x] Run `git diff --check`.
- [x] Report CRS correctness.
- [x] Report topology consistency.
- [x] Report geometry semantic explainability.
- [x] Report audit traceability.
- [x] Report performance verifiability.

## Phase 5 - Governance Registration

- [x] Update project-level source facts to register T08 as Active.
- [x] Update module inventories and doc status snapshots.
