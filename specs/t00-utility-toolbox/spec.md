# T00 Utility Toolbox 规格说明

## 1. 背景与目标

RCSD_Topo_Poc 当前需要一个轻量、可治理的项目内工具模块，用于承接数据整理、实验准备、辅助检查、问题排查与数据分析类工作，避免这类内部工具混入正式业务生产模块。

T00 的目标不是生成地图业务要素，也不是替代后续业务模块；它的目标是为项目内部辅助工具提供统一的文档入口、边界约束与后续编码门禁。

## 2. 模块定位

- 模块 ID：`T00`
- 模块名称：`Utility Toolbox / 工具集合模块`
- 模块属性：项目内工具集合模块
- 明确不是：Skill
- 明确不是：正式业务生产模块
- 明确不承担：后续地图要素生成逻辑

T00 与正式业务模块是辅助支持关系，而不是上下游业务生产关系。它服务于项目内部整理和排查工作，但不直接产出 RCSD 业务要素。

## 3. 当前范围

当前范围仅纳入一个工具：

- Tool1：Patch 数据整理脚本

本轮不预设 Tool2 及以上工具，也不为未来工具预先扩展重型框架。

## 4. Tool1 需求基线

### 4.1 目标

将“全量 Patch 矢量目录”整理为后续实验统一使用的 Patch 目录骨架，并将源 Patch 下的矢量文件归位到目标 `Vector/` 目录。

### 4.2 输入

- 源目录（Windows 口径）：`D:\TestData\POC_Data\数据整理\vectors`
- 源目录（WSL 映射口径）：`/mnt/d/TestData/POC_Data/数据整理/vectors`

输入目录下的每个一级子目录代表一个候选 Patch。

### 4.3 输出

- 目标根目录（Windows 口径）：`D:\TestData\POC_Data\patch_all`
- 目标根目录（WSL 映射口径）：`/mnt/d/TestData/POC_Data/patch_all`

目标目录结构为：

```text
<PatchID>/
  PointCloud/
  Vector/
  Traj/
```

日志与摘要落点位于目标根目录下。

### 4.4 PatchID 识别规则

- `vectors` 目录下每个一级子目录名就是一个 `PatchID`
- 当前已确认 `PatchID` 目录名均为纯数字
- 不做额外映射
- 不做重命名

### 4.5 处理步骤

1. 基于全量 Patch 矢量目录提取全量 `PatchID`
2. 在目标根目录下为每个 `PatchID` 创建目录骨架：
   - `<PatchID>/PointCloud/`
   - `<PatchID>/Vector/`
   - `<PatchID>/Traj/`
3. 将源 `<PatchID>` 目录下的所有文件拷贝到目标 `<PatchID>/Vector/`

### 4.6 覆盖策略

- 若目标 Patch 已存在，允许复跑
- 复跑时只清空目标 `<PatchID>/Vector/` 下已有内容
- 清空后重新拷贝源 `<PatchID>` 下所有文件
- `PointCloud/` 与 `Traj/` 目录只保证骨架存在，不处理其中内容

### 4.7 异常处理

- 若某个源 Patch 目录异常，则直接跳过该 Patch
- 该 Patch 记为失败
- 不影响其它 Patch 继续执行
- 异常原因必须进入日志与摘要

### 4.8 日志与摘要

最小摘要项必须包含：

- `total_patch_count`
- `success_count`
- `failure_count`
- `skip_count`
- 每个 Patch 的文件拷贝数
- 每个失败 Patch 的异常原因

统计口径必须明确：

- `success_count + failure_count = total_patch_count`
- `skip_count` 是 `failure_count` 的子类统计，不是并列主分类

### 4.9 退出口径

- 单个 Patch 失败不影响全量流程继续执行
- 全流程结束后统一汇总异常
- 全流程结束时必须能给出全量成功/失败/跳过摘要

### 4.10 运行入口风格

- 后续实现采用项目内固定脚本
- 参数集中在文件头维护
- 不要求命令行参数驱动

## 5. 非范围

Tool1 当前明确不做以下内容：

- 点云拷贝
- 轨迹拷贝
- 字段重命名
- 坐标系转换
- 几何修复
- 图层内容分析
- 深度 manifest 治理
- 复杂业务逻辑判断

## 6. 风险与边界

- 必须防止 T00 从“项目内工具集合”扩张为业务生产模块
- 必须防止 Tool1 从“目录骨架初始化 + Vector 数据归位”扩张为多步骤数据治理流水线
- Windows 路径与 WSL 执行路径需要保持一一对应，避免后续实现时误用盘符或根目录
- “异常 Patch” 的判定语义在本轮只要求可记录、可跳过、可汇总，不在本轮扩展为复杂分类体系

## 7. 进入后续阶段的门禁

满足以下条件后，T00 才可进入 Tool1 编码阶段：

1. `spec / plan / tasks` 与模块文档口径一致
2. 模块级 `architecture/*`、`README.md`、`AGENTS.md`、`INTERFACE_CONTRACT.md` 已完成基线落仓
3. Tool1 的输入、输出、覆盖、异常、摘要与非范围语义已确认
4. 已明确当前阶段只实现 Tool1，不顺带扩展 Tool2+
5. 已明确后续实现遵循“固定脚本 + 文件头集中参数”的运行风格
