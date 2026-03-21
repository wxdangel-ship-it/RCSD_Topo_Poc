# T00 Utility Toolbox 规格说明

## 1. 背景与目标

`T00` 用于承接 `RCSD_Topo_Poc` 项目内的数据整理、实验准备、辅助检查、问题排查和全局辅助图层预处理工作，避免这类工具散落在业务模块或临时脚本中。

`T00` 的目标是提供轻量、可复跑、可追溯的项目内工具集合，不直接承担地图业务要素生产。

## 2. 模块定位

- 模块名称：`T00 Utility Toolbox / 工具集合模块`
- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不承担后续地图要素生成逻辑
- `T00` 只为项目内部工具提供统一落点、边界约束和固定执行入口

## 3. 当前范围

当前纳入范围为 Tool1 至 Tool5：

- Tool1：Patch 数据整理脚本
- Tool2：全量 DriveZone 预处理与合并
- Tool3：全量 Intersection 预处理与汇总
- Tool4：一层路网增加 `patch_id`
- Tool5：一层路网增加 SW 原始 `kind`

## 4. 统一规则

### 4.1 路径口径

- Patch 子目录统一使用 `Vector/`
- 不使用 `vector/`

### 4.2 CRS 与几何处理口径

- 所有几何处理统一在目标 CRS 下进行
- Tool1 不做几何处理
- Tool2 默认目标 CRS 固定为 `EPSG:3857`
- Tool3 当前沿用既有 `EPSG:3857` 口径
- Tool4 / Tool5 在脚本顶部显式设置 `TARGET_EPSG`，默认值为 `3857`
- Tool5 的两类输入默认 CRS 分别独立配置：
  - `A200_road_patch` 默认 `EPSG:3857`
  - SW 原始路网默认 `EPSG:4326`
- 输入若非目标 CRS，先重投影到目标 CRS
- 允许最小限度几何修复，仅用于保证流程可执行
- 不做复杂人工推断式修复
- 修复失败则跳过并记录异常

### 4.3 压缩口径

- “压缩”统一定义为拓扑保持的几何简化
- 简化容差为可配置参数
- 目标是降低数据量，但不得明显改变业务形态

### 4.4 覆盖口径

- 输出已存在时，先删除再重建
- Tool1 例外：复跑时只清空目标 `<PatchID>/Vector/` 后重拷贝

### 4.5 执行体验口径

- 固定脚本入口
- 文件头集中参数
- 命令行执行过程中必须提供进度输出
- 至少体现工具开始/结束、阶段级进度、Patch 或记录级进度

## 5. Tool1 需求基线

### 5.1 目标

将全量 Patch 矢量目录整理为统一 `patch_all` 目录骨架，并将源 Patch 文件归位到目标 `Vector/` 目录。

### 5.2 输入与输出

- 源目录：`D:\TestData\POC_Data\数据整理\vectors`
- 目标根目录：`D:\TestData\POC_Data\patch_all`

目标结构：

```text
<PatchID>/
  PointCloud/
  Vector/
  Traj/
```

### 5.3 PatchID 识别规则

- `vectors` 下每个一级子目录名就是 `PatchID`
- `PatchID` 目录名均为纯数字
- 不做额外映射，不做重命名

### 5.4 处理步骤

1. 提取全量 `PatchID`
2. 为每个 `PatchID` 创建 `PointCloud/`、`Vector/`、`Traj/`
3. 将源 `<PatchID>` 目录下所有文件拷贝到目标 `<PatchID>/Vector/`

### 5.5 覆盖、异常与摘要

- 允许复跑
- 复跑时只清空目标 `<PatchID>/Vector/`
- `PointCloud/` 与 `Traj/` 只保证骨架存在
- 源 Patch 异常时跳过该 Patch，记为失败，不中断全量
- 摘要至少包含：
  - `total_patch_count`
  - `success_count`
  - `failure_count`
  - `skip_count`
  - 每个 Patch 的文件拷贝数
  - 异常原因
- 固定统计关系：
  - `success_count + failure_count = total_patch_count`
  - `skip_count` 是 `failure_count` 的子类统计，不是并列主分类

## 6. Tool2 需求基线

### 6.1 目标

对 `patch_all/<PatchID>/Vector/DriveZone.geojson` 做单 Patch 预处理，先在每个 Patch 下生成 `DriveZone_fix.geojson`，再基于所有 fix 文件做全量面合并，输出根目录全局 `DriveZone.geojson`。

### 6.2 输入与输出

- 单 Patch 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DriveZone.geojson`
- 单 Patch fix 输出：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DriveZone_fix.geojson`
- 全局输出：`D:\TestData\POC_Data\patch_all\DriveZone.geojson`
- 输出坐标必须真实为 `EPSG:3857`

### 6.3 单 Patch 处理流程

1. 读取单个 Patch 的 `DriveZone.geojson`
2. 若输入 CRS 非 `3857`，先重投影到 `3857`
3. 允许最小限度几何修复；修复失败则跳过并记录异常
4. 对单 Patch 内面进行合并
5. 合并后先膨胀 `5m`，再腐蚀 `5m`
6. `5m` 为可配置参数
7. 对处理结果做一次拓扑保持的几何简化
8. 在同目录输出 `DriveZone_fix.geojson`

### 6.4 全量处理流程

1. 收集所有成功生成的 `DriveZone_fix.geojson`
2. 基于这些 fix 结果做全量面合并
3. 全量合并完成后再做一次拓扑保持的几何简化
4. 输出根目录全局 `DriveZone.geojson`

### 6.5 缺失输入、覆盖与摘要

- 缺失 `DriveZone.geojson` 时按 `warning / skip` 处理
- 不影响全量流程继续执行
- 已存在 `DriveZone_fix.geojson` 时先删除再重建
- 已存在根目录 `DriveZone.geojson` 时先删除再重建
- 摘要至少包含：
  - `total_patch_count`
  - `input_found_count`
  - `fixed_output_count`
  - `skip_missing_count`
  - `skip_error_count`
  - `global_merge_input_count`
  - 输出要素统计
  - 异常原因摘要

## 7. Tool3 需求基线

### 7.1 目标

对 `patch_all/<PatchID>/Vector/Intersection.geojson` 做逐 Patch 预处理并汇总为全局 `Intersection.geojson`。本轮不重写 Tool3 业务规则，沿用既有基线。

### 7.2 当前稳定口径

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\Intersection.geojson`
- 输出：`D:\TestData\POC_Data\patch_all\Intersection.geojson`
- 输出 CRS：`EPSG:3857`
- 单 Patch 内逐要素做拓扑保持简化
- 保留原始属性并新增 `patchid`
- 全量阶段只汇总，不做面合并
- 缺失输入按 `warning / skip` 处理，不中断全量

## 8. Tool4 需求基线

### 8.1 目标

基于 `A200_road` 与 `rc_patch_road` 的 road 级属性关联，为一层路网增加 `patch_id`，并输出无法关联的异常结果。

### 8.2 输入与输出

- 输入一：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road.shp`
- 输入二：`D:\TestData\POC_Data\first_layer_road_net_v1_patch\rc_patch_road.shp`
- 正式输出：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch.geojson`
- 异常输出：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch_unmatched.geojson`
- 输出坐标真实写为 `TARGET_EPSG`，默认 `3857`

### 8.3 关联规则与处理要求

- 关联规则：`A200_road.id = rc_patch_road.road_id`
- 访问时需对字段大小写做兼容审计
- 输出字段统一命名为 `patch_id`
- 优先使用属性关联 / 哈希映射，不做逐条全表扫描
- 需要识别以下情况：
  - 正常唯一匹配
  - 无匹配
  - 重复但 `patch_id` 一致
  - overlap 导致同一 `road_id` 对应多个不同 `patch_id`
- overlap 情况下，不再把该 road 记为 unmatched
- overlap 情况下，`patch_id` 记录多个值，并按逗号 `,` 拼接
- unmatched 只用于无匹配或缺失关键关联值

### 8.4 摘要要求

- 摘要至少包含：
  - `total_a200_count`
  - `matched_count`
  - `unmatched_count`
  - `duplicate_road_id_count`
  - `conflicting_patch_id_count`
  - `multi_patch_assignment_count`
  - 输出路径
  - 异常说明

## 9. Tool5 需求基线

### 9.1 目标

以 Tool4 输出为输入，基于 `1m` 缓冲与 SW 原始路网空间匹配，为一层路网增加原始 `kind`。

### 9.2 输入与输出

- 输入一：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch.geojson`
- 输入二：`D:\TestData\POC_Data\first_layer_road_net_v0\SW\A200-2025M12-road.geojson`
- 输出：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch_kind.geojson`
- 输出坐标真实写为 `TARGET_EPSG`，默认 `3857`

### 9.3 处理流程

1. 读取 Tool4 输出与 SW 原始路网
2. `A200_road_patch` 默认按 `3857` 读取
3. SW 原始路网默认按 `4326` 读取
4. 将两者统一投影到 `TARGET_EPSG=3857`
5. 对每条 `A200_road_patch` 构建 `1m` 缓冲
6. 使用空间索引查找被缓冲区包含的 SW 线要素
7. 读取 SW 的 `Kind`
8. 按单个道路种别拆分 `"|"`
9. 去重后按 `"|"` 重新拼接
10. 在输出中新增 `kind`

### 9.4 约束与摘要

- SW 字段名读取需兼容 `Kind` / `kind`
- 输出字段统一命名为 `kind`
- 若某条 `A200_road_patch` 找不到任何 SW road：
  - `kind` 赋空值
  - 记入 `unmatched_kind_count`
  - 不影响全量流程
- 空间关系口径按“SW 线完全落入 Buffer”处理，可采用 `covers` / `covered_by` / `within` 等等价稳妥谓词，但必须在摘要中说明
- 必须使用空间索引
- 摘要至少包含：
  - `total_a200_patch_count`
  - `sw_feature_count`
  - `matched_kind_count`
  - `unmatched_kind_count`
  - `empty_kind_count`
  - 输出路径
  - 异常说明

## 10. 非范围

当前非范围包括：

- Tool6+
- Tool3 全量重写
- 复杂 manifest 治理
- 数据库落仓
- 复杂产线编排
- 为未来扩展提前搭重型框架
- 对 Tool1 的无关业务重构
- 对单 Patch 中间产物做超出当前需求的正式化治理

## 11. 风险与边界

- 必须防止 `T00` 从内部工具集合扩张为业务生产模块
- Tool2 的 per-patch fix 与全局输出都要可复跑，避免旧输出残留干扰
- Tool4 的 overlap `patch_id` 必须显式保留，不得 silently 丢弃
- Tool5 必须以空间索引和稳定谓词保证性能与语义一致
- 对缺失 CRS 的输入，只允许用脚本头部明确配置的默认 CRS，不得静默猜测

## 12. 进入后续阶段的门禁

满足以下条件后，可继续进入后续增量实现或扩展：

1. `spec / plan / tasks / README / AGENTS / INTERFACE_CONTRACT / architecture/*` 口径一致
2. Tool1 至 Tool5 的输入、输出、覆盖、异常与摘要语义稳定
3. 不改变 `T00` 作为内部工具模块的定位
4. 新工具进入 `T00` 前，先补规格与契约
