# T08 Preprocess Plan

## 1. Strategy

Redefine T08 as the project preprocessing module for base vector layers.

The implementation sequence is:

1. Freeze T08 module contract, Tool1 behavior, Tool2 behavior, and Tool3 behavior.
2. Create T08 module docs from the repository template.
3. Implement Tool1 / Tool2 / Tool3 module callable runners.
4. Add focused tests with synthetic vector inputs.
5. Add three root innernet scripts and register them.
6. Register T08 as an Active formal module in project source facts.
7. Run QA checks and report GIS requirements explicitly.

## 2. Boundaries

### Allowed In This Round

- `modules/t08_preprocess/**`
- `src/rcsd_topo_poc/modules/t08_preprocess/**`
- `tests/modules/t08_preprocess/**`
- `scripts/t08_tool1_shp_to_gpkg.py`
- `scripts/t08_tool2_road_preprocess.py`
- `scripts/t08_tool3_nodes_type_aggregation.py`
- project source facts and module inventories needed to register T08
- `docs/repository-metadata/entrypoint-registry.md`
- `specs/t08-preprocess/**`

### Not Allowed In This Round

- Node implementation outside Tool3 Nodes type aggregation.
- Repo CLI / tools / Makefile entrypoints.
- T00 contract changes.

## 3. Implementation Shape

Tool1 callable API:

```python
from rcsd_topo_poc.modules.t08_preprocess import run_t08_tool1_conversions
```

Tool2 callable API:

```python
from rcsd_topo_poc.modules.t08_preprocess import run_t08_road_preprocess

artifacts = run_t08_road_preprocess(
    road_input_path=...,
    patch_road_input_path=...,
    source_kind_road_path=...,
    out_root=...,
    run_id=...,
)
```

Tool2 recommended outputs:

```text
<out_root>/<run_id>/road_preprocess/
  t08_road_patch.gpkg
  t08_road_patch_unmatched.gpkg
  t08_road_patch_kind.gpkg
  t08_road_patch_summary.json
  t08_road_kind_summary.json
  t08_road_preprocess_summary.json
```

Tool3 callable API:

```python
from rcsd_topo_poc.modules.t08_preprocess import run_t08_nodes_type_aggregation
```

Tool3 recommended outputs:

```text
<out_root>/<run_id>/nodes_preprocess/
  t08_nodes_type_aggregation.gpkg
  t08_nodes_type_aggregation_summary.json
```

## 4. Verification

Minimum commands:

```bash
.venv/bin/python -m pytest tests/modules/t08_preprocess
.venv/bin/python scripts/t08_tool1_shp_to_gpkg.py --help
.venv/bin/python scripts/t08_tool2_road_preprocess.py --help
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py --help
git diff --check
```

Closeout must include the five GIS / QA checks listed in `spec.md`.
