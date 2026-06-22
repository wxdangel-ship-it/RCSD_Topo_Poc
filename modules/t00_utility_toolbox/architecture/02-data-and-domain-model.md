# 02 Data And Domain Model

## 1. 输入对象

T00 的正式输入对象都是历史支撑数据，不代表当前主业务链的 source-of-truth。

核心输入对象包括：

- Patch 目录：历史分块数据组织单元，用于归位 `Vector/` 文件和汇总 per-patch 输出。
- DriveZone / Intersection / DivStripZone：历史面数据，用于生成可追溯的 fix 或汇总成果。
- A200 Road / Node：历史一层路网对象，用于补充 patch、kind 或导出节点。
- GeoJSON：人工排查和历史工具常用轻量矢量格式。
- MIF / MID：MapInfo 文本矢量数据文件组，Tool11 以 `.mif` 为扫描入口。
- JSON / NDJSON：Tool10 上车点导出的输入载体。

## 2. 业务对象与关系

T00 处理的是支撑工具对象，不是正式业务对象：

- 工具输入：历史数据或人工排查输入。
- 工具派生输出：方便后续查看、转换或历史比较的文件。
- summary / log：说明工具实际读写、跳过、失败和计数的审计材料。

## 3. 领域分层

- 目录归位层：Tool1 只保证 Patch 目录结构可复用。
- 面数据汇总层：Tool2 / Tool3 / Tool9 只提供历史面数据 fix 和汇总。
- 字段补充层：Tool4 / Tool5 / Tool6 只为 A200 历史输入补充或导出字段。
- 格式转换层：Tool7 / Tool10 / Tool11 只转换文件表达形式，不发明业务语义。

## 4. 几何与字段语义

- Tool2 / Tool3 / Tool6 输出使用 `EPSG:3857`。
- Tool4 / Tool5 通过 `TARGET_EPSG` 控制目标 CRS，默认 `3857`。
- Tool7 优先读取 GeoJSON `crs`；缺失时按现有契约默认 `EPSG:4326`。
- Tool10 将 `data.spots[].lon/lat` 作为原始经纬度写出到 `EPSG:4326` GPKG。
- Tool11 优先保留 MIF 源 CRS；缺失时必须显式传入 `--default-crs`。

## 5. 下游数据语义

T00 输出只能作为支撑材料、历史比较或 T08 能力迁移参考。任何 T00 输出进入 T01-T10 主链前，都必须被相应正式模块重新定义为输入契约；不得因为 T00 已生成文件，就自动视为正式 handoff。
