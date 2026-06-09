# ARTIFACT_PROTOCOL Retired Historical Reference

## 状态

- 当前状态：Retired historical reference
- 退役日期：2026-06-09
- 原用途：早期外网 / 内网之间通过 `TEXT_QC_BUNDLE v1` 文本粘贴回传质检信息。

## 退役原因

项目当前已经采用文件证据包、summary、audit、review 和必要文本提炼的组合方式进行本地 case 分析、内网执行结果回传和问题复盘。旧文本粘贴协议只能表达早期小体量摘要，已经不能作为当前正式协作协议。

## 当前替代口径

- 正式证据组织见 `docs/architecture/04-evidence-and-audit.md`。
- 真实存在的 `qc-template` / `qc-demo` CLI 入口仍在 `docs/repository-metadata/entrypoint-registry.md` 登记为历史兼容工具。
- 历史审计材料中出现的 `TEXT_QC_BUNDLE` 仅用于追溯，不代表当前项目协议。
