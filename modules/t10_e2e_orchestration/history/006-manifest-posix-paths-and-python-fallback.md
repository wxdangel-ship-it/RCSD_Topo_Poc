# 006 Manifest POSIX Paths And Python Fallback

## 时间

2026-06-15

## 背景

T10 负责端到端 Case package 与 Case runner 的输入输出结构审计。Windows 本地测试暴露两个结构问题：

- manifest / package 中的产物路径会按 Windows 反斜杠写出，和 package 内相对路径约定不一致。
- Windows 侧访问 WSL 风格 `.venv/bin/python` 可能抛出 `OSError`，导致 runner 在还未执行阶段前失败，不能形成可审计的 failed / blocked stage 记录。

## 业务逻辑变更

- T10 Case runner 的产物路径文本统一使用 POSIX 风格 `/`，保持跨 Windows / WSL / 内网 Linux 的 manifest 可比性。
- T10 Case evidence package 的 `package_path` 统一使用 POSIX 相对路径。
- T10 Python 解释器选择在 `.venv/bin/python` 不可访问时回退到 `python3`，避免环境路径异常绕过 T10 阶段状态记录。

## 边界

- 不改变 T01-T09 任一业务模块算法。
- 不改变 T10 的阶段顺序、handoff 文件集合或 Case package 范围选择。
- 不新增正式入口。

## 验证

- `python -m pytest tests/modules/t10_e2e_orchestration -q`
- `bash -n scripts/t10_run_innernet_full_pipeline.sh && bash -n scripts/t01_run_full_data.sh`
