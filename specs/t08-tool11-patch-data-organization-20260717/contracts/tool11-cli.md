# Tool11 CLI 契约

## 命令

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root <原始数据根> \
  --output-root <全量整理根> \
  --experiment-output-root <实验数据根>
```

## 参数

- `--source-root`：必填，直接包含 `<PatchID>` 子目录的原始数据根。
- `--output-root`：必填，全量整理输出根。
- `--experiment-output-root`：必填，实验 Patch 独立输出根。
- `--experiment-patch-id`：可重复；出现任意一次时整体替换默认 6 Patch 列表。
- `--summary-output`：可选，显式 summary 路径；文件名必须以 `_tool11.json` 结尾。
- `--overwrite`：可选，校验通过后整体替换两个已有输出根和显式 summary。
- `--progress-interval-files`：可选，处理多少文件输出一次进度，默认 `100`。

## 退出码

- `0`：两个输出根和 summary 均成功发布。
- `2`：参数、预检、复制、校验或发布失败。

## 标准输出

成功时 stdout 输出 JSON：

```json
{
  "output_root": "...",
  "experiment_output_root": "...",
  "summary_json": "..."
}
```

进度与错误写 stderr。失败错误必须包含 summary 路径（summary 本身无法写入的文件系统错误除外）。

## 覆盖语义

- 默认任一正式输出根存在即失败。
- `--overwrite` 不允许边复制边删除旧成果。
- 新的两个暂存根全部校验成功后才进入发布。
- 发布中任一步失败时恢复已有根；临时/备份目录按 run token 精确清理。
