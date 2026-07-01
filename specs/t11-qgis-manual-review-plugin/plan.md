# Plan：T11 QGIS 人工 Relation 审计插件

## 1. 插件位置

新增两个边界清晰的目录：

```text
src/rcsd_topo_poc/modules/t11_manual_relation_review/qgis_review/
qgis_plugins/t11_relation_review/
```

`qgis_review` 是可测试核心；`qgis_plugins/t11_relation_review` 是 QGIS 插件工程。插件不新增 `scripts/` 入口，不新增 CLI 子命令。

## 2. 核心模块边界

| 模块 | 责任 |
|---|---|
| `ids.py` | `selected_ids` 解析、拼接、RCSDNode/RCSDRoad feature selection 提取。 |
| `task_index.py` | 从一张或多张 T11 relation 缺口 Excel 读取任务、排序、按 `target_id` 去重、导出辅助 JSON；QGIS UI 单次只传入一张审计 Excel。 |
| `excel_sync.py` | XLSX 行级读取、可写检测、首次写入备份、仅更新人工字段。 |
| `layer_validation.py` | 图层数据源、CRS、必需字段校验；不依赖 QGIS。 |

## 3. QGIS 插件边界

| 文件 | 责任 |
|---|---|
| `metadata.txt` | QGIS 插件元数据。 |
| `__init__.py` | QGIS `classFactory` 入口。 |
| `plugin.py` | 插件生命周期、左侧任务管理 Dock 和底部任务处理 Dock 的注册与移除。 |
| `dock_widget.py` | 双 Dock UI、任务分页、图层绑定、定位、高亮、selection 写入。 |

QGIS Dock 使用 QGIS 图层管理器已有图层，不主动改变样式或图层顺序；任务管理保持分页列表，任务处理使用屏幕底部横向栏，点击任务后默认缩放到约 `1:1000`。

## 4. Excel 同步策略

1. 打开 workbook 时先执行可写检测。
2. 每个插件会话对每个 workbook 首次写入前复制到 `_t11_qgis_backups/`。
3. 每次编辑只写目标 Excel row 的 `manual_relation_type / selected_ids / comment`。
4. 写入通过修改 XLSX 内部 XML 完成，保留其它 zip entry、sheet 结构和 data validation。
5. 若 workbook 被 Excel 或其它程序占用导致写入失败，QGIS UI 切换为只读并提示错误。

## 5. 任务排序与去重

任务来源仅限当前两张 Excel，但插件 UI 单次只加载其中一张进行修订。排序键：

1. `segment_priority_rank` 升序。
2. `segment_priority_bucket` 升序。
3. `segment_length_m` 降序。
4. `swsd_segment_id` 升序。
5. 原始 workbook 顺序与 Excel 行号。

排序后按 `target_id` 保留第一条。该条的 `workbook_path / excel_row` 是后续唯一写入目标。

## 6. 测试策略

- 纯 Python：Excel 读写、任务去重排序、`NULL` 状态、selected_ids、图层校验。
- 插件结构：metadata 解析、必需文件存在、QGIS 插件入口可静态 import。
- 605415675：若本地没有两张 Excel，则用 T11 callable 从指定 case root 重新生成，并带入已有人工 CSV；再用核心加载和写入测试验证。
- PyQGIS：若 `/usr/bin/python3` 可 import `qgis`，执行插件 import 级验证；否则记录未执行原因。

## 7. 605415675 验证路径

读取输入：

```text
/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t10_e2e_case_runs/t10_all_cases_c5085f0_20260630_181345/cases/605415675
/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t11_manual_consumption_605415675_add_612312328_20260701T070108Z/t11_manual_relation_605415675.csv
```

验证输出写到当前 worktree：

```text
outputs/_work/t11_qgis_manual_review_plugin_605415675_<timestamp>/
```

## 8. 入口与文档同步

QGIS 插件是正式插件加载面，不新增 repo CLI 或 scripts 入口。本轮同步：

- `modules/t11_manual_relation_review/SPEC.md`
- `modules/t11_manual_relation_review/INTERFACE_CONTRACT.md`
- `modules/t11_manual_relation_review/architecture/03-solution-strategy.md`
- `docs/repository-metadata/entrypoint-registry.md`
