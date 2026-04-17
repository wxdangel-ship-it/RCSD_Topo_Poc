# t03_virtual_junction_anchor

> 本文件是 `t03_virtual_junction_anchor` 的操作者入口说明。正式契约以 `INTERFACE_CONTRACT.md` 为准，长期设计以 `architecture/*` 为准。

## 1. 当前定位

- T03 当前只承接 `Phase A / Step3 legal-space baseline only`
- 正式输入契约固定为 Anchor61 `case-package`
- 线程 `REQUIREMENT.md` 本轮整体不启用，不作为当前模块事实源
- 本轮交付：
  - 独立 `Step1/Step2` 最小支撑
  - `Step3 legal space`
  - 批量运行
  - case 级输出
  - 平铺 PNG 审查目录

## 2. 官方入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

## 3. 默认路径

- 默认输入根：`/mnt/e/TestData/POC_Data/T02/Anchor`
- 默认输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a`

## 4. 典型运行方式

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space \
  --case-root /mnt/e/TestData/POC_Data/T02/Anchor \
  --workers 4 \
  --out-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a \
  --run-id t03_phase_a_demo \
  --debug
```

## 5. 当前正式边界

- `Step3` 只输出 `allowed space / negative mask / step3 status`
- 不实现 `Step4/5/6/7`
- 不允许把 `cleanup / trim / review_mode / stage4 聚合` 前置成 `Step3` 成立条件
- 平铺 PNG 审查目录是正式交付物之一
