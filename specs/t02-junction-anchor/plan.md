# T02 文档先行计划

> 本文件是 T02 stage1 初始基线的变更计划工件。当前正式模块运行与契约以 `modules/t02_junction_anchor/*` 为准。

## 1. 当前阶段（历史变更上下文）

- 当前阶段：`requirements baseline bootstrap`
- 工作方式：文档先行
- 本轮只完成 T02 需求基线文档落仓

## 2. 本轮计划目标

1. 固化 T02 模块业务定位。
2. 固化 T02 的阶段拆分与当前边界。
3. 固化阶段一 `DriveZone / has_evd gate` 的输入、规则、输出、统计与审计口径。
4. 补入 stage1 新增总汇总项 `all__d_sgrade`。
5. 冻结 stage2 anchor recognition / anchor existence 的文档基线。
6. 冻结 stage2 新增输入 `RCSDIntersection.geojson`、`nodes.is_anchor`、错误态与优先级口径。
7. 将 T02 文档基线收口到“可进入对应实现任务书准备”。

## 3. 本轮边界

- 不进入 Python / CLI / 算法实现。
- 不新增运行入口。
- 不新增测试代码。
- 不实现阶段二锚定主逻辑。
- 不定义成果概率 / 置信度实现。
- 不把 stage2 扩写成最终锚定算法。
- 不修改 T01 文档。

## 4. 预期后续阶段

1. 阶段一文档确认
2. 文档落仓复核
3. 阶段一补充汇总实现任务书准备
4. 阶段一补充实现
5. 阶段二 anchor recognition 实现任务书准备
6. 阶段二实现
7. 阶段二之后的需求继续澄清

说明：

- 当前只走到“文档落仓复核”。
- “阶段一补充实现”“阶段二实现”与“阶段二之后的需求继续澄清”都不在本轮执行。

## 5. 当前不进入的事项

- 当前不进入阶段二实现。
- 当前不进入概率实现。
- 当前不补写未经确认的锚定几何、候选生成、候选排序或评分公式。

## 6. 后续仍可继续澄清但不阻断编码任务书准备的事项

- 环岛代表 node 的后续完善空间。
- 阶段一审计留痕的稳定落盘形态。
- 阶段二 `node_error_1 / node_error_2` 的稳定文件命名与最小审计字段。
- 缺失 CRS 时由谁负责补齐数据质量或在任务书中定义执行失败处理。

## 7. 当前完成标准

- `spec.md`、`plan.md`、`tasks.md` 落仓。
- `AGENTS.md`、`INTERFACE_CONTRACT.md`、`README.md` 落仓。
- `overview.md` 与 `000-bootstrap.md` 记录阶段边界与上游歧义。
- 文档之间口径一致。
- stage1 字段映射、`s_grade` 写法、代表 node 规则、空目标路口口径、`all__d_sgrade` 与 `EPSG:3857` 口径已冻结。
- stage2 的 `RCSDIntersection.geojson`、`nodes.is_anchor`、`yes/no/fail1/fail2/null`、错误态与优先级已冻结为文档基线。
- 本轮后可进入阶段一补充汇总与阶段二 anchor recognition 的实现任务书准备。
- 全程无代码、测试、入口改动。
