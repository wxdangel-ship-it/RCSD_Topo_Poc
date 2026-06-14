# 001 Phase2 RCSDRoad Out Mixed Geometry

## 日期
- 2026-06-10

## 背景
- T10 Case `74155468` 在 T05 Phase2 真实执行阶段失败。
- 错误发生在写出 `rcsdroad_out.gpkg`：输入 RCSDRoad 中存在 `MultiLineString`，输出 schema 固定为 `LineString`，Fiona 拒绝写入。

## 根因
- Phase2 的 copy-on-write 输出应保留原始 RCSDRoad 几何表达；裁剪数据与上游资料中可能存在 `LineString / MultiLineString` 混合。
- 原写出层把 `rcsdroad_out.gpkg` 约束为单一 `LineString` schema，属于输出承载能力不足，不是道路属性语义问题。

## 本次边界
- 不修改输入 `RCSDRoad / RCSDNode`。
- 不拆解、合并或重塑 `MultiLineString` 几何。
- 不改变 split 生成的新 road 仍为 `LineString` 的拓扑规则。

## 实际变更
- `rcsdroad_out.gpkg` 写出 schema 改为 `Unknown`，允许 copy-on-write 主网同时承载 `LineString` 与 `MultiLineString`。
- `rcsdroad_split.gpkg` 仍保持 `LineString`，因为 split 产物来自明确的线段切分。

## 验证
- 新增 Phase2 回归用例，输入 `MultiLineString` RCSDRoad 后确认 `rcsdroad_out.gpkg` 保留 `MultiLineString`。
- 待复跑 T10 Case，确认 T05 Phase2 可以完成写出并进入 T06。
