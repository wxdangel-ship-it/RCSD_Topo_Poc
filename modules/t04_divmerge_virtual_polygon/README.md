# t04_divmerge_virtual_polygon

> 本文件是 `t04_divmerge_virtual_polygon` 的操作者入口说明。长期源事实以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

## 1. 当前定位

- T04 是原 T02 Stage4 的模块化继承与重构版。
- 当前正式范围已扩展到 `Step1-7`：
  - `Step1 = candidate admission`
  - `Step2 = high-recall local context`
  - `Step3 = topology skeleton`
  - `Step4 = fact event interpretation + review outputs`
  - `Step5 = geometric support domain`
  - `Step6 = polygon assembly`
  - `Step7 = final acceptance + publishing`
- 当前已具备 `Step5-7` 本地实现与 internal full-input 执行骨架；`Step1-4` 维持既有稳定执行面。
- 当前正式输入覆盖单 case `case-package` 与 internal full-input；full-input 通过 repo 级 shell/watch 包装进入 T04 私有 runner，不新增 repo 官方 CLI。

## 2. 当前入口状态

- 当前 **没有 repo 官方 CLI**。
- 当前稳定执行面是模块内 Python runner：
  - `run_t04_step14_batch(...)`
  - `run_t04_step14_case(...)`
  - `run_t04_internal_full_input(...)`
- internal full-input repo 级脚本入口：
  - `scripts/t04_run_internal_full_input_8workers.sh`
  - `scripts/t04_watch_internal_full_input.sh`
  - `scripts/t04_run_internal_full_input_innernet_flat_review.sh`
- 上述脚本不是 repo 官方 CLI 子命令；执行逻辑保持在 T04 私有 orchestration 内，并已登记到 `docs/repository-metadata/entrypoint-registry.md`。

## 3. 默认输入与输出

- 默认本地 case 根：`/mnt/e/TestData/POC_Data/T02/Anchor_2`
- 默认输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch`
- 默认 review 结构：
  - `cases/<case_id>/final_review.png`
  - `cases/<case_id>/event_units/<event_unit_id>/step4_review.png`
  - `step4_review_flat/*.png`
  - `step4_review_index.csv`
  - `step4_review_summary.json`
- internal full-input 最终目视审计结构：
  - `visual_checks/final_by_state/accepted/*.png`
  - `visual_checks/final_by_state/rejected/*.png`
  - `visual_checks/final_flat/*.png`
  - `visual_checks/final_index.csv`
  - `visual_checks/final_index.json`

## 4. 当前正式边界

- 只承接 `diverge / merge / continuous complex 128`。
- Step1 不做事实解释与几何裁决。
- Step2 只定义 SWSD 侧负向上下文；RCSD 负向语义后移。
- Step4 只做事实解释、正向 RCSD 选取与一致性检查，不做最终 polygon。
- Step5 构建 `must_cover / allowed_growth / forbidden / terminal_cut`。
- Step6 在 Step5 约束内组装最终单连通面。
- Step7 只发布 `accepted / rejected` 二态结果与伴随审计材料。

## 5. 文档阅读顺序

1. `architecture/01-introduction-and-goals.md`
2. `architecture/03-context-and-scope.md`
3. `architecture/04-solution-strategy.md`
4. `architecture/05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
