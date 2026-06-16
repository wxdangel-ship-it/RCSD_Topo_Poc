# 022 Text Bundle Byte Stable Output

## 时间

2026-06-15

## 背景

端到端审计要求各模块输入输出结构可追溯，T06 text bundle 负责把 Step1/Step2/Step3 的运行证据、输入 manifest、重放脚本与必要输入切片打包为可转移文本包。

在 Windows 环境下，`Path.write_text(..., encoding="utf-8")` 会按文本模式写出，换行可能从 LF 转换为 CRLF。T06 text bundle 的分片算法按 `text.encode("utf-8")` 计算字节数，导致报告的 `max_part_size_bytes` 与实际落盘文件大小可能不一致，进而出现“分片报告未超限、实际文件超限”的结构审计失败。

## 业务逻辑变更

- 对受 `max_text_size_bytes` 约束的 bundle 正文输出统一使用 UTF-8 bytes 写出。
- 单文件 bundle 与 split part bundle 均返回实际写出字节数。
- split bundle 的 `part_size_bytes` 与 `max_part_size_bytes` 改为以实际落盘 bytes 为准。

## 边界

- 不改变 T06 Step1/Step2/Step3 的替换判定、buffer 提取、group replacement 或 F-RCSD 输出逻辑。
- 不改变文本包格式、解码逻辑、输入切片策略或 replay command 结构。
- JSON size report 与 decode manifest 仍按普通 UTF-8 文本写出；它们不参与 `max_text_size_bytes` 分片约束。

## 验证

- `python -m pytest tests/modules/t06_segment_fusion_precheck/test_text_bundle.py::test_t06_input_text_bundle_slices_by_center_and_keeps_segment_dependencies -q`
- `python -m pytest tests/modules/t06_segment_fusion_precheck -q`
