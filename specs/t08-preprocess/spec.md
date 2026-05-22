# T08 Preprocess Specification

**Feature Branch**: `codex/t08-redefinition`
**Status**: Implementing - Tool1 / Tool2 / Tool3 / Tool4
**Scope Mode**: SpecKit implementation

## 1. Module Definition

`t08_preprocess` is the project preprocessing module for base vector data before downstream topology modules consume it.

T08 is not a temporary utility toolbox. It may expose tool-style command scripts, but these tools are project-formal preprocessing components and their contracts belong to the business data chain.

## 2. Current Scope

### 2.1 Tool1 - Basic Vector Format Conversion

Tool1 converts one or more vector inputs between the current preprocessing exchange formats.

- Inputs MUST be provided as WSL paths by command parameters.
- Multiple `.shp`, `.geojson`, `.json`, and `.gpkg` inputs are accepted in one run.
- `.shp` inputs MUST output `<input_dir>/<input_stem>.gpkg`.
- `.geojson / .json` inputs MUST output `<input_dir>/<input_stem>.gpkg`.
- `.gpkg` inputs MUST output `<input_dir>/<input_stem>.geojson`.
- Tool1 MUST NOT merge multiple inputs into one output and MUST NOT require an output directory or per-input output path parameters.
- Tool1 MUST fail before writing if same-run inputs would create duplicate output paths or overwrite another same-run input.
- Tool1 preserves input CRS by default; a target EPSG may be supplied when an explicit reprojection is needed.
- If an input has no CRS metadata, the caller MUST provide a default CRS parameter.

### 2.2 Tool2 - Road Preprocess

Tool2 migrates the current Road part from T00 Tool4 / Tool5 and changes its execution contract:

- Add `patch_id` to raw Road by joining `road.id = patch_road.road_id`.
- Add original Road `kind` by spatially matching the patch-enriched Road with a source Road layer that contains `Kind / kind`.
- All inputs MUST be GPKG.
- Final vector outputs MUST be GPKG.
- Final processing/output CRS MUST be `EPSG:3857`.
- All input/output paths MUST be command parameters. No hard-coded internal path remains in T08 implementation.
- Inputs MAY come from different project data sources, but the first implementation only relies on generic Road fields, not source-specific semantics.

### 2.3 Tool3 - Nodes Type Aggregation

Tool3 implements the first frozen Nodes preprocessing scope:

- Add or overwrite `kind_2` and `grade_2` by copying `kind` and `grade`.
- Preserve original `kind / grade`.
- Aggregate roundabout groups into `kind_2 = 64` mainnodes using T01 roundabout topology rules.
- Aggregate continuous complex div/merge groups into `kind_2 = 128` mainnodes using T04/T02 continuous chain topology rules.
- Output a copy-on-write Nodes GPKG in `EPSG:3857`.
- Use Roads GPKG only as topology reference; Tool3 MUST NOT output or modify Roads.
- All input/output paths MUST be command parameters.

Tool3 depends on these fields:

- Nodes: `id / kind / grade`, optional `mainnodeid / has_evd / is_anchor / subnodeid`.
- Roads: `id / snodeid / enodeid / direction`, optional `roadtype`.

### 2.4 Tool4 - Junction Type Repair Error Detection

Tool4 implements the first frozen junction type repair scope. This round only detects errors and outputs audit rows; it does not automatically fix `kind`.

- Inputs MUST be GPKG.
- Nodes input depends on `id / kind`, with optional `mainnodeid`.
- Roads input depends on `id / snodeid / enodeid / direction`.
- Output MUST be `nodes_error.gpkg` in `EPSG:3857`.
- Summary MUST record input/output paths, field audit, CRS, semantic node count, error count by type, direction errors, performance timings, and Road read mode.
- T-junction error: `kind = 2048` with either `in_degree != 2` or `out_degree != 2`.
- Cross-junction error: `kind = 4` with `in_degree = 2` and `out_degree = 2`.
- Continuous divmerge error: `kind = 16` diverge with two outgoing roads, traced through degree-2 connectors to a `kind = 8` merge within `100m` with two incoming roads, and matching T-shape topology.

Other automatic Node repair remains deferred until a later task defines:

- target Node fields to add/update;
- source field semantics;
- input/output layer names and formats;
- copy-on-write behavior;
- audit and acceptance criteria.

## 3. EntryPoints

This round adds four repo-level scripts, all explicitly authorized by the task:

- `.venv/bin/python scripts/t08_tool1_vector_convert.py`
- `.venv/bin/python scripts/t08_tool2_road_preprocess.py`
- `.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py`
- `.venv/bin/python scripts/t08_tool4_junction_type_repair.py`

Both scripts MUST accept WSL paths and MUST NOT contain internal hard-coded data paths.

## 4. Non-Goals

- Do not implement automatic Node repair outside the explicitly defined Tool4 error detection output.
- Do not add repo CLI, `tools`, `Makefile` targets, module `run.py`, or module `__main__.py`.
- Do not modify T00 Tool4 / Tool5 contracts.
- Do not infer upstream field semantics from local samples or smoke outputs.
- Do not add dependencies.

## 5. Product View

Users need a reusable preprocessing module for Road and Node data. For this round, the user must be able to execute four innernet scripts with explicit WSL paths:

- Tool1 converts SHP / GeoJSON to GPKG and GPKG to GeoJSON, writing outputs next to each input file.
- Tool2 preprocesses Road data using GPKG inputs and writes GIS-ready `EPSG:3857` GPKG outputs.
- Tool3 preprocesses Nodes type fields using Nodes/Roads GPKG inputs and writes GIS-ready `EPSG:3857` Nodes GPKG output.
- Tool4 detects junction type errors using Nodes/Roads GPKG inputs and writes GIS-ready `EPSG:3857` `nodes_error.gpkg`.

Tool2 accepted outcome:

- `road_patch.gpkg`: raw Road with `patch_id`.
- `road_patch_unmatched.gpkg`: raw Road records that did not match Patch Road.
- `road_patch_kind.gpkg`: `road_patch` records with source `kind`.
- JSON summaries for patch join, kind enrichment, and combined run.

Tool3 accepted outcome:

- `nodes_type_aggregation.gpkg`: Nodes copy-on-write output with `kind_2 / grade_2 / mainnodeid / subnodeid`.
- `nodes_type_aggregation_summary.json`: field audit, CRS audit, roundabout groups, complex div/merge groups, candidate counts, chain counts, and updated node counts.

Tool4 accepted outcome:

- `nodes_error.gpkg`: error semantic junction rows with `error_type / error_reason / in_degree / out_degree / related_node_ids / related_road_ids`.
- `junction_type_repair_summary.json`: field audit, CRS audit, semantic node count, error count by type, direction errors, and performance timings.

## 6. Architecture View

T08 implementation lives under:

```text
src/rcsd_topo_poc/modules/t08_preprocess/
```

Module documentation should live under:

```text
modules/t08_preprocess/
```

The implementation should keep the write set narrow:

- T08 module docs;
- T08 implementation package;
- T08 focused tests;
- four root scripts;
- entrypoint registry;
- this SpecKit task directory.

The four root scripts are official entrypoints and MUST be registered in `docs/repository-metadata/entrypoint-registry.md`.

## 7. Development View

Tool2 implementation must preserve these validated T00 behaviors:

- field names are resolved case-insensitively for `id`, `road_id`, `patch_id`, and `Kind / kind`;
- multiple `patch_id` values are sorted and joined by comma;
- `kind` values are split by `|`, deduplicated, and joined by `|`;
- missing Road-to-Patch join is reported in an unmatched output layer;
- CRS normalization happens before spatial matching.
- command scripts print stage progress while preserving machine-readable artifact output;
- summary records total elapsed time, stage elapsed time, throughput, and spatial candidate counts.

Implementation may refactor shared vector read/write helpers inside T08 only if it keeps files below repository size limits.

Tool1 implementation must:

- read one or more SHP / GeoJSON / GPKG inputs;
- write one same-directory, same-stem output per input using the supported target format;
- stream features from source to target to avoid loading full inputs into memory;
- print progress from the command script while preserving machine-readable summary output;
- record per-file summary rows;
- avoid changing CRS unless `target_epsg` is explicitly provided.

Tool3 implementation must:

- read Nodes/Roads GPKG inputs;
- write one Nodes GPKG output in `EPSG:3857`;
- initialize `kind_2 / grade_2` from `kind / grade`;
- apply T01 roundabout mainnode aggregation from `roadtype bit3`;
- apply T04/T02 complex div/merge mainnode aggregation from continuous directed road chains;
- preserve raw `kind / grade` and leave Roads untouched;
- record summary counts and group audit rows.
- command scripts print stage progress while preserving machine-readable artifact output;
- summary records total elapsed time, stage timings, throughput, candidate counts, chain counts, and updated node counts.
- continuous-chain component assembly should avoid repeated full edge scans per component.

Tool4 implementation must:

- read Nodes/Roads GPKG inputs;
- read Road GPKG through the lightweight SQLite path when standard GPKG metadata is available, keeping only required fields, length, and direction vector for topology;
- write one `nodes_error.gpkg` output in `EPSG:3857`;
- compute semantic junction in/out degree from Road `direction`;
- detect wrong T, wrong cross, and continuous divmerge-as-T errors;
- preserve raw inputs and leave Roads untouched;
- record summary counts, error rows, field audit, CRS audit, direction errors, and performance timings.

## 8. Testing View

Tests must be synthetic and local:

- create temp Shapefile / GeoJSON / GPKG inputs;
- assert Tool1 writes same-directory GPKG outputs for SHP / GeoJSON inputs and same-directory GeoJSON outputs for GPKG inputs;
- assert Tool2 output suffixes are `.gpkg`;
- assert Tool2 output CRS resolves to `EPSG:3857`;
- assert Tool3 output CRS resolves to `EPSG:3857`;
- assert scripts use parameterized temp paths;
- assert `patch_id`, unmatched reason, and `kind` values;
- assert Tool3 writes `kind_2 / grade_2 / mainnodeid` for roundabout and complex div/merge groups;
- assert Tool4 writes wrong T, wrong cross, and continuous divmerge error rows into `nodes_error.gpkg`;
- assert JSON summary counts.
- assert Tool2 / Tool3 / Tool4 progress output and performance summary fields.

No test may require internal data paths.

## 9. QA View

Closeout must explicitly report:

- **CRS correctness**: source CRS resolution, reprojection to `EPSG:3857`, output CRS metadata.
- **Topology consistency**: no silent geometry-topology rewrite for Tool1 conversion, Tool2 Road preprocessing, Tool3 Nodes type aggregation, or Tool4 error detection.
- **Geometry semantic explainability**: `kind` comes from declared source Road spatial match; Tool3 `kind_2` aggregation comes from declared T01/T04 topology rules; Tool4 errors come from declared degree and continuous-divmerge rules, not sample inference.
- **Audit traceability**: input paths, output paths, parameters, field resolution, counts, and unmatched reasons are recorded.
- **Performance verifiability**: source/target feature counts and spatial-index candidate matching counts are available in summary.

## 10. Acceptance Criteria

1. T08 module definition is documented before implementation.
2. Tool1, Tool2, Tool3, and Tool4 are implemented as T08 formal preprocessing tools.
3. Automatic Node repair outside Tool4 error detection remains explicitly deferred.
4. Tool1 converts SHP / GeoJSON to same-directory same-name GPKG files and GPKG to same-directory same-name GeoJSON files with parameterized inputs only.
5. Tool2 uses only GPKG inputs and writes GPKG `EPSG:3857` outputs.
6. Tool3 uses only GPKG inputs and writes Nodes GPKG `EPSG:3857` output.
7. Tool4 uses only GPKG inputs and writes `nodes_error.gpkg` `EPSG:3857` output.
8. Focused tests cover Tool1, Tool2, Tool3, and Tool4 behavior without internal data.
