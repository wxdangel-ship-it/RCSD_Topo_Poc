# T08 Tool10 轨迹聚合计划

## 1. 实施顺序

1. 基于真实轨迹审计冻结输入、Z、CRS、排序、切段和单 GPKG 落盘口径。
2. 更新 T08 模块源事实，显式登记 `raw_dat_pose.gpkg` 命名特例。
3. 实现 `run_t08_trajectory_aggregation` 与正式脚本入口。
4. 增加合成测试，覆盖成功路径和全部 fail-fast 边界。
5. 复制真实来源 Patch 到 `outputs/_work` 后验证，不改写 Highway 原始数据。
6. 执行 T08 回归、入口登记、文件体量、GIS 五项 QA 与 diff 检查。

## 2. 允许范围

- `specs/t08-tool10-trajectory-aggregation/**`
- `modules/t08_preprocess/**`
- `src/rcsd_topo_poc/modules/t08_preprocess/**`
- `tests/modules/t08_preprocess/**`
- `scripts/t08_tool10_trajectory_aggregation.py`
- `scripts/t08_tool10_run_patches_innernet.sh`
- `docs/repository-metadata/entrypoint-registry.md`

## 3. 排除范围

- T00 Tool10 及其契约；
- T01-T07、T09-T11 业务实现；
- 项目 CLI、Makefile 与其他长期入口；
- Highway 仓库代码和真实来源数据的写入。

## 4. 验证命令

```bash
.venv/bin/python -m pytest tests/modules/t08_preprocess/test_tool10_trajectory_aggregation.py
.venv/bin/python -m pytest tests/modules/t08_preprocess
.venv/bin/python scripts/t08_tool10_trajectory_aggregation.py --help
bash -n scripts/t08_tool10_run_patches_innernet.sh
git diff --check
```
