# T00 Utility Toolbox 规格说明

## 1. 背景与目标

`RCSD_Topo_Poc` 需要一个轻量、可持续增量扩展的项目内工具模块，用于承接数据整理、实验准备、辅助检查、问题排查、全局辅助图层预处理和数据分析类工作，避免这些工具散落到业务模块或临时脚本中。

T00 的目标不是生成业务要素，也不是替代正式业务模块；它承担的是项目内部工具的统一落点、范围约束和可执行实现基线。

## 2. 模块定位

- 模块 ID：`T00`
- 模块名称：`Utility Toolbox / 工具集合模块`
- 模块属性：项目内工具集合模块
- 明确不是：Skill
- 明确不是：正式业务生产模块
- 明确不承担：后续地图要素生产逻辑

T00 与正式业务模块是辅助支持关系。它为项目内部预处理和排查提供公共工具，但不直接产出 RCSD 业务结果。

## 3. 当前范围

当前已纳入三个工具：

- Tool1：Patch 数据整理脚本
- Tool2：全量 DriveZone 的预处理与汇总输出
- Tool3：全量 Intersection 的预处理与汇总

后续新增工具必须单独补规格，不得在本轮实现中顺带扩展 Tool4+。

## 4. 统一规则

### 4.1 路径口径

- Patch 子目录统一使用 `Vector/`
- 不使用 `vector/`

### 4.2 CRS 与几何处理口径

- 所有几何处理统一在 `EPSG:3857` 下进行
- 输入若非 `EPSG:3857`，先重投影到 `EPSG:3857`
- 允许最小限度几何修复，仅用于保证流程可执行
- 不做复杂人工推断式修复
- 修复失败则跳过并记录异常

### 4.3 压缩口径

- “压缩”统一定义为：在 `EPSG:3857` 下进行的、拓扑保持的几何简化
- 简化容差为可配置参数
- 目标是降低数据量，但不得明显改变业务形态

### 4.4 输出覆盖口径

- 输出已存在时，先删除再重建

### 4.5 执行体验口径

- 命令行执行过程中必须提供进度输出
- 至少体现阶段级与 Patch 级进度

## 5. Tool1 需求基线

### 5.1 目标

将“全量 Patch 矢量目录”整理成后续实验统一使用的 Patch 目录骨架，并将源 Patch 文件归位到目标 `Vector/` 目录。

### 5.2 输入与输出

- 源目录（Windows）：`D:\TestData\POC_Data\数据整理\vectors`
- 源目录（WSL）：`/mnt/d/TestData/POC_Data/数据整理/vectors`
- 目标根目录（Windows）：`D:\TestData\POC_Data\patch_all`
- 目标根目录（WSL）：`/mnt/d/TestData/POC_Data/patch_all`

目标目录结构：

```text
<PatchID>/
  PointCloud/
  Vector/
  Traj/
```

### 5.3 PatchID 识别规则

- `vectors` 目录下每个一级子目录名就是一个 `PatchID`
- `PatchID` 目录名均为纯数字
- 不做额外映射，不做重命名

### 5.4 处理步骤

1. 提取全量 `PatchID`
2. 在目标根目录下为每个 `PatchID` 创建 `PointCloud/`、`Vector/`、`Traj/`
3. 将源 `<PatchID>` 目录下的所有文件拷贝到目标 `<PatchID>/Vector/`

### 5.5 覆盖、异常与摘要

- 允许复跑
- 复跑时只清空目标 `<PatchID>/Vector/`，然后重拷贝
- `PointCloud/` 与 `Traj/` 只保证骨架存在，不处理内容
- 源 Patch 异常时跳过该 Patch，记为失败，不中断全量
- 摘要至少包含：
  - `total_patch_count`
  - `success_count`
  - `failure_count`
  - `skip_count`
  - 每个 Patch 的文件拷贝数
  - 异常原因
- 统计关系固定为：
  - `success_count + failure_count = total_patch_count`
  - `skip_count` 是 `failure_count` 的子类统计，不是并列主分类

### 5.6 运行风格与非范围

- 运行风格：固定脚本、文件头集中参数、不要求命令行参数驱动
- 当前非范围：
  - 点云拷贝
  - 轨迹拷贝
  - 字段重命名
  - 坐标系转换
  - 图层内容分析
  - 深度 manifest 治理
  - 复杂业务逻辑判断

## 6. Tool2 需求基线

### 6.1 目标

对 `patch_all/<PatchID>/Vector/DriveZone.geojson` 做单 Patch 预处理，并将各 Patch 结果汇总到一个全局 `DriveZone.geojson`。

### 6.2 输入与输出

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DriveZone.geojson`
- 输出：`D:\TestData\POC_Data\patch_all\DriveZone.geojson`
- 输出坐标必须真实为 `EPSG:3857`

### 6.3 单 Patch 处理流程

1. 读取单个 Patch 的 `DriveZone.geojson`
2. 若输入 CRS 非 `3857`，先重投影到 `3857`
3. 允许最小限度几何修复；修复失败则跳过并记录异常
4. 对单 Patch 内面做合并
5. 合并后先膨胀 `5m`，再腐蚀 `5m`
6. `5m` 为可配置参数
7. 对处理后的结果做一次拓扑保持的几何简化
8. 单 Patch 结果直接作为全局输出文件中的独立要素参与汇总，不强制单独持久化

### 6.4 全量处理流程

1. 将所有单 Patch 处理后的 `DriveZone` 结果汇总到一个文件
2. 不做全量面合并
3. 输出文件中的每个要素对应一个单 Patch 处理结果
4. 输出一个全局 `DriveZone.geojson`

### 6.5 缺失输入、覆盖与摘要

- 缺失 `DriveZone.geojson` 时按 `warning / skip` 处理
- 不影响全量流程继续执行
- 旧输出已存在时先删除再重建
- 摘要至少包含：
  - `total_patch_count`
  - `input_found_count`
  - `processed_patch_count`
  - `skip_missing_count`
  - `skip_error_count`
  - 输出要素统计
  - 异常原因摘要

## 7. Tool3 需求基线

### 7.1 目标

对 `patch_all/<PatchID>/Vector/Intersection.geojson` 做逐要素预处理，再汇总成一个全局 `Intersection.geojson`。

### 7.2 输入与输出

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\Intersection.geojson`
- 输出：`D:\TestData\POC_Data\patch_all\Intersection.geojson`
- 输出坐标必须真实为 `EPSG:3857`

### 7.3 单 Patch 处理流程

1. 读取单个 Patch 的 `Intersection.geojson`
2. 若输入 CRS 非 `3857`，先重投影到 `3857`
3. 允许最小限度几何修复；修复失败则跳过并记录异常
4. 对每个面对象做拓扑保持的几何简化
5. 保留原始属性
6. 新增 `patchid` 字段，便于追溯来源

### 7.4 全量处理流程

1. 将所有 Patch 下处理后的 `Intersection` 要素汇总到一个文件
2. 不做面合并
3. 输出一个全局 `Intersection.geojson`

### 7.5 缺失输入、覆盖与摘要

- 缺失 `Intersection.geojson` 时按 `warning / skip` 处理
- 不影响全量流程继续执行
- 旧输出已存在时先删除再重建
- 若原始属性存在 `patchid` 冲突风险，应采用最小破坏策略并在摘要中说明
- 摘要至少包含：
  - `total_patch_count`
  - `input_found_count`
  - `processed_patch_count`
  - `skip_missing_count`
  - `skip_error_count`
  - 输出要素统计
  - 异常原因摘要

## 8. 非范围

当前不纳入范围：

- Tool4 及以上工具
- 复杂 manifest 治理
- 复杂产线编排
- 数据库落仓
- 强制持久化 Tool2 / Tool3 的单 Patch 中间结果
- 对 Tool1 做无关业务重构

## 9. 风险与边界

- 必须防止 T00 从“工具集合模块”扩张为业务生产模块
- 必须防止 Tool2 / Tool3 因未来需求想象而提前搭成重型框架
- `GeoJSON` 缺失 CRS 时需要依赖脚本头部配置的默认 CRS 口径，不得在代码中静默猜测
- Tool2 / Tool3 的单 Patch 中间结果默认只作为过程数据，不应被误当成正式输出契约

## 10. 后续扩展门禁

满足以下条件后，才可继续向 T00 增加新工具或扩展现有工具：

1. `spec / plan / tasks / README / AGENTS / INTERFACE_CONTRACT / architecture/*` 口径一致
2. Tool1 / Tool2 / Tool3 的输入、输出、统一几何口径与覆盖策略已稳定
3. 新能力不会改变 T00 的“内部工具模块”定位
4. Tool4+ 已单独补规格与边界说明
