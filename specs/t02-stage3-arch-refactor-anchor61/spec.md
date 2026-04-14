# T02 / Stage3 Anchor61 架构优化规格

## 1. 文档定位

- 类型：结构重构规格
- 范围：`t02_junction_anchor` 的 `Stage3`
- 目标：以 Anchor61 为唯一正式验收基线，完成 Stage3 执行骨架、输出链与审计链的契约化重构

## 2. 当前审计前提

- 当前 Stage3 状态为“部分落地”，不是“重构完成”
- 当前主导矛盾是“骨架问题大于参数问题”
- 当前首要根因是“多因叠加，但以代码实现问题为主”
- 当前简单场景几何能力为“部分落地，但关键控制不足”
- 当前应先做架构优化，不应继续做 case patch

## 3. 正式验收基线

- `E:\TestData\POC_Data\T02\Anchor`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor`）下的 61 个 case，是当前 Stage3 唯一正式验收基线
- 本轮正式验收只认 `case-package`
- `test_virtual_intersection_full_input_poc.py` 当前仅作 fixture / dev-only / regression 使用
- full-input 当前不是 Stage3 正式交付基线

## 4. 本轮范围

- Step3 / Step5 / Step6 / Step7 执行边界硬化
- `virtual_intersection_poc.py` 从 monolith 收回 orchestrator
- `review_index.json / review_summary.md / summary.json` 单轨语义收口
- `kind` provenance 收口
- Anchor61 manifest 与正式验收层接线

## 5. 非目标

- 不做 Stage4 重构
- 不做 full-input 真实正式交付基线建设
- 不做参数调优轮
- 不做单个 case 特判
- 不通过新增 late pass 继续承担业务语义

## 6. 结构重构目标

### 6.1 Step3

- 从 snapshot builder 升级为 canonical legal-space layer
- 输出唯一 legal activity space / allowed drivezone / hard boundary 结果
- 后续步骤不得反向扩大 Step3

### 6.2 Step5

- 统一 foreign 事实源
- 明确区分 baseline foreign、blocking foreign、Step6 final residue
- Step7 不再重新解释 Step5 foreign subtype

### 6.3 Step6

- 升级为 canonical geometry controller
- 将 `late_*cleanup* / trim / cap / mask / tail clip` 收编为：
  - `primary solve`
  - `bounded optimizer`
  - `final validation`
- bounded optimizer 只允许修边，不允许修业务语义
- simple `single_sided_t_mouth` 与 simple `center_junction` 必须暴露可验证的几何控制结果

### 6.4 Step7

- 去掉 legacy fallback 主导权
- 只消费 `Step3Result / Step4Result / Step5Result / Step6Result`
- 不再以 raw `acceptance_reason/status` 作为主要裁决来源
- 只负责结果三态、根因层、目视分类与业务结果分类

## 7. 输出与审计收口目标

- `review_index.json` 只消费 canonical `Step7Result + AuditRecord`
- `summary.json` 以三态主口径为主，不再以旧 success/failure 二元口径主导
- `success` 布尔若保留，只能作为兼容字段，不得与 tri-state 冲突
- `kind` 优先来自 `nodes.kind`，缺失时 fallback `nodes.kind_2`，并显式输出 `kind_source`

## 8. 基线验证目标

- Anchor61 全量 case-package 正式验收
- full-input tests 仅作 regression
- 简单场景专项样本：
  - `698330`
  - `706389`
  - `584253`
  - `10970944`
- 失败锚点专项样本：
  - `520394575`
