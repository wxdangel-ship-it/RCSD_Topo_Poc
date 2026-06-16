# 005 - Innernet full pipeline stage manifest

## 时间

2026-06-14

## 背景

内网全量链路已经通过 `scripts/t10_run_innernet_full_pipeline.sh` 串联 T08、T01、T07、T03、T04、T05、T06、T09，但原始 manifest 主要是 flat `inputs / outputs`。不同模块输出目录和文件命名差异较大，下游审计需要根据目录名和脚本变量猜测 handoff 角色。

## 业务逻辑变更

- 保留原有 flat `inputs / outputs`，兼容已有消费方。
- 在同一个 `t10_innernet_full_pipeline_manifest.json` 中新增 `stage_order / stages`。
- 每个阶段记录统一结构：
  - `stage_id`
  - `module_id`
  - `status`
  - `stdout_log`
  - `inputs`
  - `outputs`
  - `params`
  - `execution_context`
- `run_logged` 在阶段失败时写入最小失败 stage record，方便定位失败阶段日志。
- 阶段成功后写入完整 handoff record，覆盖 T08、T01、T07 Step1/2、T03、T04、T05、T07 Step3、T06 Step1/2、T06 Step3、T09。

## 不变项

- 不新增执行入口。
- 不改变 T01-T09 任一模块算法。
- 不改变各模块既有输出物理路径。

## 审计收益

全量审计和下游脚本可以优先消费 `stages.<stage_id>.inputs / outputs / execution_context`，不再根据各模块五花八门的目录名推断 handoff 文件角色。
