# T00 - INTERFACE_CONTRACT

## 1. 模块概览

- 模块 ID：`t00_utility_toolbox`
- 模块名称：`T00 Utility Toolbox`
- 当前工具：
  - Tool1 `Patch 数据整理脚本`
  - Tool2 `全量 DriveZone 的预处理与汇总输出`
  - Tool3 `全量 Intersection 的预处理与汇总`

本文件用于固化 T00 当前稳定的输入、输出、覆盖、跳过与摘要语义。实现细节可继续补足，但不得偏离本契约。

## 2. 通用约束

- 路径口径：Patch 子目录统一使用 `Vector/`
- CRS 口径：所有几何处理统一在 `EPSG:3857`
- 修复口径：允许最小修复，仅用于保证流程可执行；修复失败则跳过并记录异常
- 压缩口径：统一为拓扑保持的几何简化
- 覆盖口径：旧输出已存在时先删除再重建
- 执行体验：命令行输出至少包含当前工具开始/结束、当前阶段、Patch 进度和最终统计

## 3. Tool1 契约

### 3.1 输入

- 源目录（Windows）：`D:\TestData\POC_Data\数据整理\vectors`
- 源目录（WSL）：`/mnt/d/TestData/POC_Data/数据整理/vectors`
- `PatchID` 识别方式：一级子目录名；目录名必须为纯数字

### 3.2 输出

- 目标根目录（Windows）：`D:\TestData\POC_Data\patch_all`
- 目标根目录（WSL）：`/mnt/d/TestData/POC_Data/patch_all`
- 正式输出：

```text
<PatchID>/
  PointCloud/
  Vector/
  Traj/
```

### 3.3 覆盖、异常与摘要

- 复跑时只清空目标 `<PatchID>/Vector/`
- 源 Patch 异常时跳过并记失败，不中断全量
- 摘要最少包含：
  - `total_patch_count`
  - `success_count`
  - `failure_count`
  - `skip_count`
  - 每个 Patch 的文件拷贝数
  - 异常原因
- 固定统计关系：
  - `success_count + failure_count = total_patch_count`
  - `skip_count` 是 `failure_count` 的子类统计

## 4. Tool2 契约

### 4.1 输入与输出

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DriveZone.geojson`
- 正式输出：`D:\TestData\POC_Data\patch_all\DriveZone.geojson`
- 输出坐标必须真实为 `EPSG:3857`

### 4.2 单 Patch 处理

- 读取单个 Patch 的 `DriveZone.geojson`
- 若输入 CRS 非 `3857`，先重投影到 `3857`
- 允许最小限度几何修复；失败则跳过该 Patch 并记异常
- 对单 Patch 面进行合并
- 合并后执行 `+5m / -5m`
- 再做一次拓扑保持的几何简化

### 4.3 全量处理

- 将所有单 Patch 的处理结果汇总到一个文件
- 不做全量面合并
- 输出文件中的每个要素对应一个单 Patch 处理结果
- 输出一个全局 `DriveZone.geojson`

### 4.4 覆盖、缺失输入与摘要

- 旧输出已存在时先删除再重建
- 缺失 `DriveZone.geojson` 时按 `warning / skip` 处理，不影响全量继续执行
- 摘要最少包含：
  - `total_patch_count`
  - `input_found_count`
  - `processed_patch_count`
  - `skip_missing_count`
  - `skip_error_count`
  - 输出要素统计
  - 异常原因摘要

## 5. Tool3 契约

### 5.1 输入与输出

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\Intersection.geojson`
- 正式输出：`D:\TestData\POC_Data\patch_all\Intersection.geojson`
- 输出坐标必须真实为 `EPSG:3857`

### 5.2 单 Patch 处理

- 读取单个 Patch 的 `Intersection.geojson`
- 若输入 CRS 非 `3857`，先重投影到 `3857`
- 允许最小限度几何修复；失败则跳过该 Patch 并记异常
- 对每个面对象做拓扑保持的几何简化
- 保留原始属性，并新增 `patchid`

### 5.3 全量处理

- 将所有 Patch 下处理后的 `Intersection` 要素汇总到一个文件
- 不做面合并
- 输出一个全局 `Intersection.geojson`

### 5.4 覆盖、缺失输入、属性与摘要

- 旧输出已存在时先删除再重建
- 缺失 `Intersection.geojson` 时按 `warning / skip` 处理，不影响全量继续执行
- 原始属性默认保留
- `patchid` 冲突时应采用最小破坏策略，并在摘要中说明
- 摘要最少包含：
  - `total_patch_count`
  - `input_found_count`
  - `processed_patch_count`
  - `skip_missing_count`
  - `skip_error_count`
  - 输出要素统计
  - 异常原因摘要

## 6. 持久化输出边界

- Tool1：Patch 骨架与 `Vector/` 归位是正式输出
- Tool2：根目录全局 `DriveZone.geojson` 是正式输出
- Tool3：根目录全局 `Intersection.geojson` 是正式输出
- Tool2 / Tool3 的单 Patch 处理中间结果默认不是契约级正式输出

## 7. 非范围契约

当前不承诺以下能力：

- Tool4+
- 复杂 manifest 治理
- 数据库落仓
- 强制持久化 Tool2 / Tool3 的单 Patch 中间结果
- 超出最小修复边界的人工推断式修复

## 8. 后续实现注意事项

- 参数名、日志文件名和具体 CLI 形式可继续在脚本中补足
- GeoJSON 缺失 CRS 时，允许通过脚本头部配置默认 CRS，但不得在实现中静默猜测
- 任何新增能力若触及非范围项，必须先更新规格文档并重新评审
