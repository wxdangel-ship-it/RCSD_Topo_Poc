# Tasks：T11 QGIS 人工 Relation 审计插件

## Specify

- [x] 限定当前只服务两张 T11 relation 缺口 Excel。
- [x] 固化 Excel 是最终事实源，插件只做地图化编辑入口。
- [x] 固化人工字段语义、`NULL` 字符串、多选 ID 和重复 `target_id` 策略。
- [x] 固化 GIS / 拓扑质量边界。

## Plan

- [x] 决定核心模块与 QGIS 插件目录。
- [x] 决定不新增 CLI / scripts 入口。
- [x] 决定 Excel XML 级单元格写入，避免新增 `openpyxl` 依赖。
- [x] 决定 605415675 输出写入当前 worktree。

## Implement phase 1：纯 Python 核心

- [x] 新增 `ids.py`。
- [x] 新增 `excel_sync.py`。
- [x] 新增 `task_index.py`。
- [x] 新增 `layer_validation.py`。
- [x] 新增核心单元测试。

## Implement phase 2：QGIS 插件骨架

- [x] 新增 `qgis_plugins/t11_relation_review/metadata.txt`。
- [x] 新增 QGIS `classFactory`。
- [x] 新增插件生命周期文件。
- [x] 新增左侧任务管理 Dock 与底部任务处理 Dock。
- [x] 任务管理 Dock 单次只加载一张审计 Excel。
- [x] Setup 区可折叠，并在加载任务后自动收起。
- [x] 任务管理 Dock 提供全局字号控制，并同步到任务处理 Dock。
- [x] 任务列表单行展示人工数据符号、目标和 SegmentID。
- [x] 任务处理 Dock 按摘要、编辑字段和分组操作按钮组织，并为按钮提供 tooltip。

## Implement phase 3：图层绑定、定位、高亮、selection 提取

- [x] 任务管理 Dock 支持五类图层绑定。
- [x] 任务管理 Dock 支持字段/CRS/路径校验。
- [x] 任务处理 Dock 支持定位到 SWSD 语义路口或 Segment。
- [x] 任务点击定位后显式居中、保持 SWSD 要素选中，并默认缩放到约 `1:1000`。
- [x] 任务处理 Dock 支持高亮已有 `selected_ids`。
- [x] 任务处理 Dock 支持从 RCSDNode / RCSDRoad selection 填入 `selected_ids`。

## Implement phase 4：Excel 即时同步

- [x] 打开时检测 workbook 可写。
- [x] 首次写入前创建备份。
- [x] 编辑人工字段后立即写入 Excel。
- [x] 写入后刷新任务完成状态。
- [x] 清空、标记 `NULL`、标记 `uncertain` 可用。

## QA

- [x] 运行纯 Python 单元测试。
- [x] 检查插件文件结构与 metadata。
- [x] 执行 PyQGIS import 级验证或记录未执行原因。
- [x] 生成/继承 605415675 两张 Excel。
- [x] 验证任务去重、已有人工显示、`NULL` 状态、写入首行、T11/T05 消费兼容。
