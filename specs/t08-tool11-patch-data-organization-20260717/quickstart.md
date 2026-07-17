# Tool11 快速运行

## 已确认内网目录一键运行

在 WSL 的仓库根目录执行：

```bash
bash scripts/t08_tool11_run_innernet.sh
```

默认输入为 `D:\TestData\数据整理\20260715\20260715\rcsd_tar_gz`，全量输出为 `D:\TestData\POC_QA\Patch_all`。脚本默认全量-only，不校验或生成实验 Patch；自动做 WSL 路径转换并写持久控制台日志。默认拒绝覆盖，确认替换既有全量根时才使用 `OVERWRITE=1 bash scripts/t08_tool11_run_innernet.sh`。

## 通用 Python 入口全量-only

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root /mnt/d/path/to/source_patches \
  --output-root /mnt/d/path/to/organized_patches
```

## 显式覆盖已有全量根

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root /mnt/d/path/to/source_patches \
  --output-root /mnt/d/path/to/organized_patches \
  --overwrite
```

## 可选启用实验 Patch

```bash
.venv/bin/python scripts/t08_tool11_patch_data_organization.py \
  --source-root /mnt/d/path/to/source_patches \
  --output-root /mnt/d/path/to/organized_patches \
  --experiment-output-root /mnt/d/path/to/experiment_patches \
  --experiment-patch-id 5524185996921171 \
  --experiment-patch-id 5724833136255764
```

内网封装如需恢复固定 6 Patch 实验模式，可显式设置 `T08_TOOL11_EXPERIMENT_OUTPUT_ROOT`；缺省时保持全量-only。

运行完成后，以 stdout 返回的 `summary_json` 为审计入口。不要仅凭目录存在判断成功。
