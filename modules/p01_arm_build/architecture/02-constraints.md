# 02 约束

## 业务约束

- 只做 P01-A，不扩展 P01-B。
- 不实现 Arm 配准、Movement、禁行迁移或通行能力裁决。
- `FinalArm = InitialArm`，Arm 级兜底合并只保留占位。
- 右转专用道 / 渠化右转只有字段明确可识别时才排除。
- `kind` 只能作为提示，不能单独裁决。
- `grade / grade_2` 不进入 Arm 构建主规则。

## 工程约束

- 文档在 `modules/p01_arm_build/`。
- 实现在 `src/rcsd_topo_poc/modules/p01_arm_build/`。
- 测试在 `tests/modules/p01_arm_build/`。
- 本轮不新增正式 CLI、scripts、Makefile 目标、模块 `__main__.py` 或模块 `run.py`。
- 源码文件写入前必须做字节数自检。

## GIS / 拓扑约束

- CRS 必须写入 preflight 与输出审计。
- trace 必须保持拓扑连续，不做 silent fix。
- 几何只用于 review 和辅助定位，不用于右转反推或 Arm 主构建。
- 输出必须记录输入、参数、run id、case id、trace、decision、issue。
