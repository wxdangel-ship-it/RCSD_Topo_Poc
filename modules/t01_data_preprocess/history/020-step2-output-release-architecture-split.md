# 020 Step2 输出与 Release 拆分

## 背景
- `step2_segment_poc.py` 体量长期超过 `100 KB`
- 当前文件同时承担：
  - pair validation / trunk / segment_body 判定
  - release compact
  - 输出写盘
  - 仲裁审计构造
- 在 `XXXS5 / XXXS7` 修复后继续堆叠逻辑，会放大回归半径

## 第一轮拆分
- 新增 `step2_release_utils.py`
  - 抽取 validation release compact 相关 helper
- 新增 `step2_output_utils.py`
  - 抽取 Step2 输出写盘、GeoJSON/CSV builders、仲裁审计输出
- `step2_segment_poc.py`
  - 保留业务判定与编排

## 当前收益
- `Step2` 的非判定型共性逻辑已脱离主文件
- 后续可以继续按子域拆分：
  - rule gates
  - validation core
  - arbitration support

## 后续迭代建议
1. 收敛 `step2_segment_poc.py` 中的 gate / barrier helper
2. 拆分 validation core 与 arbitration orchestration
3. 保持样例最终 Segment 非回退作为每轮硬闸
