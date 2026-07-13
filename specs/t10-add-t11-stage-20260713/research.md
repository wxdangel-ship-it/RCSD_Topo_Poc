# T10 增加 T11 阶段研究记录

## 已确认事实

- 当前 Case runner stage order 在 `case_runner.py::T10_E2E_STAGE_ORDER` 中定义，T06 Step3 后直接进入 T09 Step1/2。
- 当前 innernet full pipeline 的 normalize/order/resume、manifest stage order 与执行块均未登记 T11。
- `case_runner_pipeline.py` 当前工作树大小 `58,733` 字节，不能承载完整 T11 adapter。
- `scripts/t10_run_innernet_full_pipeline.sh` 当前工作树大小 `51,499` 字节，可在 60KiB 内增加最小阶段编排。
- T11 正式入口单用例模式接受 `--t10-case-root / --out-root / --case-id`，输出 JSON 包含 `run_root / candidates_csv / summary_json`。
- T11 对 Case runner layout 已有显式路径；对 innernet full layout 当前主要依赖递归 fallback，需补显式相对路径。

## 不变量

- T11 只读 T10/T01-T06 产物，不修改上游。
- T09 继续直接消费 T06 F-RCSD 与 SWSD handoff，不消费 T11 candidates。
- T07 Step3 保持可选。
- 不新增正式入口。
