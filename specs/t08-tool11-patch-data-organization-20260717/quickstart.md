# Tool11 快速运行

## 默认 6 个实验 Patch

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root /mnt/d/path/to/source_patches \
  --output-root /mnt/d/path/to/organized_patches \
  --experiment-output-root /mnt/d/path/to/experiment_patches
```

## 显式覆盖已有两个输出根

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root /mnt/d/path/to/source_patches \
  --output-root /mnt/d/path/to/organized_patches \
  --experiment-output-root /mnt/d/path/to/experiment_patches \
  --overwrite
```

## 自定义实验 Patch 列表

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root /mnt/d/path/to/source_patches \
  --output-root /mnt/d/path/to/organized_patches \
  --experiment-output-root /mnt/d/path/to/experiment_patches \
  --experiment-patch-id 5524185996921171 \
  --experiment-patch-id 5724833136255764
```

运行完成后，以 stdout 返回的 `summary_json` 为审计入口。不要仅凭目录存在判断成功。
