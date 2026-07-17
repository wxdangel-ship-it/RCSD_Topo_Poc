# Tool11 CLI 契约

## 命令

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root <原始数据根> \
  --output-root <全量整理根>
```

已确认内网目录的 WSL 固定场景封装：

```bash
bash scripts/t08_tool11_run_innernet.sh
```

封装默认使用 `D:\TestData\数据整理\20260715\20260715\rcsd_tar_gz` 和 `D:\TestData\POC_QA\Patch_all` 运行全量-only，不校验或生成实验 Patch；路径可通过 `T08_TOOL11_SOURCE_ROOT / T08_TOOL11_OUTPUT_ROOT` 覆盖，显式设置 `T08_TOOL11_EXPERIMENT_OUTPUT_ROOT` 才启用固定 6 Patch 实验模式。

## 参数

- `--source-root`：必填，直接包含 `<PatchID>` 子目录的原始数据根。
- `--output-root`：必填，全量整理输出根。
- `--experiment-output-root`：可选，实验 Patch 独立输出根；缺省时为全量-only。
- `--experiment-patch-id`：可重复且要求同时提供实验根；出现任意一次时整体替换默认 6 Patch 列表。
- `--summary-output`：可选，显式 summary 路径；文件名必须以 `_tool11.json` 结尾。
- `--overwrite`：可选，校验通过后整体替换所有已请求的已有输出根和显式 summary。
- `--progress-interval-files`：可选，处理多少文件输出一次进度，默认 `100`。

## 退出码

- `0`：所有已请求输出根和 summary 均成功发布。
- `2`：参数、预检、复制、校验或发布失败。

WSL 封装保留正式 Python 入口退出码；封装自身的路径、环境或参数预检失败也返回 `2`。

## 标准输出

成功时 stdout 输出 JSON；全量-only 的 `experiment_output_root` 为 `null`，启用实验模式时为对应绝对路径：

```json
{
  "output_root": "...",
  "experiment_output_root": null,
  "summary_json": "..."
}
```

进度与错误写 stderr。失败错误必须包含 summary 路径（summary 本身无法写入的文件系统错误除外）。

## 覆盖语义

- 默认任一已请求正式输出根存在即失败。
- `--overwrite` 不允许边复制边删除旧成果。
- 所有已请求暂存根全部校验成功后才进入发布。
- 发布中任一步失败时恢复已有根；临时/备份目录按 run token 精确清理。
- WSL 封装默认全量-only 且 `OVERWRITE=0`；只有显式 `OVERWRITE=1` 才传入 `--overwrite`，完整控制台输出必须写入持久日志。
