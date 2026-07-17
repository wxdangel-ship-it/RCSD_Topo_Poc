# T08 Tool11 数据模型

## PatchPlan

- `patch_id`: Patch 目录名。
- `source_patch_dir`: 源 Patch 绝对路径。
- `files`: 要复制的 `PatchFilePlan`。
- `directories`: 要创建的 SWSD/RCSD/FRCSD 相对目录集合，包含空目录。
- `ignored_frcsd_entries`: `rc_sw_gd_merge` 中非白名单条目。
- `errors`: 本 Patch 预检错误。
- `is_experiment`: 是否属于实验列表。

## PatchFilePlan

- `role`: `SWSD | RCSD | FRCSD`。
- `relative_path`: 相对于角色根的 POSIX 路径。
- `source_path`: 源文件绝对路径。
- `main_relative_path`: 相对于主输出根的路径。

## FileAudit

- `patch_id / role / relative_path`
- `source_path / main_output_path / experiment_output_path`
- `size_bytes`
- `source_sha256 / main_output_sha256 / experiment_output_sha256`
- `source_stable_during_copy`
- `verified`

## Tool11Summary

- `tool / generated_at_utc / run_token / status / error`
- `inputs / outputs / parameters`
- `root_audit / patches / file_audit`
- `counts`
- `integrity_audit`
- `gis_audit`
- `performance`
- `environment`

## 发布状态

```text
preflight -> staging -> verified -> committing -> passed
        \-> failed
```

只有 `verified` 可以进入 `committing`。`failed` 不允许同时存在本轮新发布的部分正式根。
