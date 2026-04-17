# T03 / Phase A plan

## 1. 文档与治理

- 先落仓 spec-kit 三件套。
- 新建 `modules/t03_virtual_junction_anchor/` 文档骨架。
- 同步项目治理文档与入口注册表，将 T03 登记为 Active。

## 2. 模块实现

- 新建 `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/`。
- 实现：
  - `case_loader`
  - `step1_context`
  - `step2_template`
  - `step3_engine`
  - `render`
  - `writer`
  - `batch_runner`
- 在 `src/rcsd_topo_poc/cli.py` 新增 `t03-step3-legal-space`。

## 3. 输出结构

- run root：
  - `preflight.json`
  - `summary.json`
  - `step3_review_index.csv`
  - `step3_review_flat/`
  - `cases/<case_id>/...`
- 每个 case 固定 7 个业务输出。

## 4. 验证

- 补齐 CLI / loader / writer / state mapping / batch smoke 测试。
- 使用系统 `python3` 跑测试与真实 Anchor61。
- 验证平铺 PNG、索引、summary 与 case 级产物完整。

## 5. 发布

- 分支：`codex/t03-phasea-step3-legal-space`
- 建议 commit 拆分：
  1. spec-kit + 模块文档 + 治理注册
  2. 模块骨架 + CLI + loader/writer
  3. Step3 引擎 + 渲染 + flat 输出
  4. 测试 + 61 case 验证 + thread sync
- push 后创建 Draft PR。
