# P02 武汉内网 Case 执行入口实施计划

## 1. 技术方案

- 新增唯一 repo 入口 `scripts/p02_run_wuhan_internal_case.py`。
- P02 内部分离端点白名单、T 型人工修正、总编排和 QGIS 工程构建 callable。
- 使用现有 T08 脚本、T01 CLI 和 T05/T06 callable，不复制业务算法。
- 输出固定为 `<out-root>/<run-id>/02_tool1...14_qgis`，逐阶段 manifest 可在失败后定位。

## 2. 治理检查

- 已由用户明确授权新增长期入口。
- 同轮更新 P02 README/SPEC/architecture/INTERFACE_CONTRACT、局部 AGENTS 和 entrypoint registry。
- 所有源码/脚本写入前先检查当前字节数；新增文件起始为 0 字节。
- 新文件保持低于 100KB，不改变 code-size audit 超阈值表。

## 3. 验证顺序

1. P02 单元测试。
2. 入口 `--help` 与四文件阻断测试。
3. 武汉原始数据 `qgis-mode=skip` 全链路回放。
4. 使用本机 QGIS Python 对打包结果生成/回读 `.qgz`。
5. T08/T01/T05/T06 聚焦回归。
6. 入口注册、文件体量、JSON/XML/datasource 和 Git 状态审计。
7. 提交并推送当前 P02 分支。

## 4. 风险

- 内网 QGIS Python 不在 PATH：正式入口失败并提示 `--qgis-python`，前序成果保留。
- Windows/WSL 投影浮点差异：业务硬门禁使用离散计数、状态和 ID 归属，不比较二进制 GPKG。
- 缺少道路面/导流带/RCSDIntersection：继续显式跳过 T03/T04/T07，不生成伪成果。
