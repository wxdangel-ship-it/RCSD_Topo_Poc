# t04_divmerge_virtual_polygon

> 本文件是 `t04_divmerge_virtual_polygon` 的操作者入口说明。长期源事实以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

## 1. 当前定位

- T04 是原 T02 Stage4 的模块化继承与重构版。
- 当前正式范围只到 `Step1-4`：
  - `Step1 = candidate admission`
  - `Step2 = high-recall local context`
  - `Step3 = topology skeleton`
  - `Step4 = fact event interpretation + review outputs`
- 本轮不进入 `Step5-7`。
- 当前正式输入以单 case `case-package` 为准；future full-input 只在文档中保留工程边界，不在本轮新增官方入口。

## 2. 当前入口状态

- 当前 **没有 repo 官方 CLI**。
- 本轮正式执行面是模块内 Python runner：
  - `run_t04_step14_batch(...)`
  - `run_t04_step14_case(...)`
- 因为没有新增官方入口，本轮不会更新 `docs/repository-metadata/entrypoint-registry.md`。

## 3. 默认输入与输出

- 默认本地 case 根：`/mnt/e/TestData/POC_Data/T02/Anchor_2`
- 默认输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch`
- 默认 review 结构：
  - `cases/<case_id>/step4_review_overview.png`
  - `cases/<case_id>/event_units/<event_unit_id>/step4_review.png`
  - `step4_review_flat/*.png`
  - `step4_review_index.csv`
  - `step4_review_summary.json`

## 4. 当前正式边界

- 只承接 `diverge / merge / continuous complex 128`。
- Step1 不做事实解释与几何裁决。
- Step2 只定义 SWSD 侧负向上下文；RCSD 负向语义后移。
- Step4 只做事实解释、正向 RCSD 选取与一致性检查，不做最终 polygon。

## 5. 文档阅读顺序

1. `architecture/01-introduction-and-goals.md`
2. `architecture/03-context-and-scope.md`
3. `architecture/04-solution-strategy.md`
4. `architecture/05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
