# 当前超阈值代码 / 脚本文件审计

## 范围

- 审计日期：2026-03-25
- 阈值：单文件超过 `100 KB`

## 结果

| 路径 | 体量 | 当前判断 | 建议 |
|---|---|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `157685` bytes | 已构成结构债 | 后续优先拆分 `support selection / validation / render / bundle glue`，避免继续在单文件累加策略分支 |

说明：

- `virtual_intersection_poc.py` 当前承载了单 `mainnodeid` 虚拟路口 POC 的输入读取、局部 patch、RC 关联、polygon-support、校验、render 与状态输出，多职责已明显耦合。
