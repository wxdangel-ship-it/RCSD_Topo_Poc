# 002 内网包装脚本 WSL 路径大小写归一

- 时间：2026-06-13
- 背景：991176 通过 T10 单 Case 端到端重跑时，T01 通过后 T07 阶段立即失败，stdout 显示 `[BLOCK] PYTHON_BIN must point to repo .venv/bin/python`。T10 runner 的 `cwd` 使用 `/mnt/c/Users/.../RCSD_Topo_Poc`，而传入的 `.venv/bin/python` 路径为 `/mnt/c/users/.../rcsd_topo_poc/.venv/bin/python`，二者在 Windows/WSL 挂载盘上指向同一位置，但字符串大小写不同。
- 根因：`scripts/t07_run_semantic_junction_anchor_innernet.sh` 对 `PYTHON_BIN` 做原始字符串比较，未考虑 WSL `/mnt/<drive>/...` 路径大小写不稳定，导致合法 repo `.venv/bin/python` 被误拦截。
- 变更：新增 `path_compare_key`，先用 `realpath -sm` 做语法归一；仅对 `/mnt/<drive>/...` 形式的 Windows 挂载路径执行大小写无关比较。普通 Linux 路径保持大小写敏感。通过校验后仍强制使用 `$REPO_DIR/.venv/bin/python`，不放宽到任意系统解释器。
- 安全边界：不新增执行入口，不改变 T07 业务算法，不改变输入输出契约；只修复 T10/内网包装调用时的 WSL 路径大小写兼容问题。
- 验证：后续使用 T10 单 Case 端到端重跑 991176，T07 不再因 `PYTHON_BIN` 路径大小写误判阻断。
