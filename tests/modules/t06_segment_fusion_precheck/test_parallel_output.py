from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.parallel_output import (
    FeatureTripletJob,
    publish_feature_triplets,
)


def test_publish_feature_triplets_writes_independent_jobs(tmp_path) -> None:
    jobs = {
        name: FeatureTripletJob(
            stem=name,
            features=[
                {
                    "type": "Feature",
                    "properties": {"id": name},
                    "geometry": LineString([(0, 0), (1, 0)]),
                }
            ],
            fieldnames=["id"],
        )
        for name in ("first", "second")
    }

    paths = publish_feature_triplets(step_root=tmp_path, jobs=jobs, max_workers=2)

    assert list(paths) == ["first", "second"]
    assert all(path_set["gpkg"].is_file() for path_set in paths.values())
    assert all(path_set["csv"].is_file() for path_set in paths.values())
    assert all(path_set["json"].is_file() for path_set in paths.values())
