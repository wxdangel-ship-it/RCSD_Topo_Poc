# T00 - INTERFACE_CONTRACT

## 1. 模块与工具名称

- 模块 ID：`t00_utility_toolbox`
- 模块名称：`T00 Utility Toolbox`
- 当前工具：Tool1 `Patch 数据整理脚本`

本文件用于固化 Tool1 当前已确认的输入、输出、覆盖、异常与摘要契约。实现细节在编码阶段补足，但不得偏离本契约语义。

## 2. Tool1 输入契约

### 2.1 源目录

- 源目录（Windows 口径）：`D:\TestData\POC_Data\数据整理\vectors`
- 源目录（WSL 映射口径）：`/mnt/d/TestData/POC_Data/数据整理/vectors`

### 2.2 PatchID 识别方式

- 源目录下每个一级子目录名就是一个 `PatchID`
- 当前已确认 `PatchID` 目录名均为纯数字
- 不做额外映射
- 不做重命名

## 3. 输出契约

### 3.1 目标根目录

- 目标根目录（Windows 口径）：`D:\TestData\POC_Data\patch_all`
- 目标根目录（WSL 映射口径）：`/mnt/d/TestData/POC_Data/patch_all`

### 3.2 目录骨架结构

```text
<PatchID>/
  PointCloud/
  Vector/
  Traj/
```

### 3.3 Vector 数据归位

- 将源 `<PatchID>` 目录下的所有文件拷贝到目标 `<PatchID>/Vector/`
- `PointCloud/` 与 `Traj/` 仅保证骨架存在，不处理内容

## 4. 覆盖契约

- 允许复跑
- 若目标 Patch 已存在，复跑时只清空目标 `<PatchID>/Vector/`
- 清空后重新拷贝源 `<PatchID>` 下所有文件
- 不清空 `PointCloud/` 与 `Traj/` 的内容

## 5. 异常契约

- 源 Patch 目录异常时，跳过该 Patch
- 被跳过的 Patch 记入失败
- 单个 Patch 失败不得中断全量流程
- 全流程结束后统一汇总异常原因

## 6. 摘要契约

摘要最少包含以下统计字段：

- `total_patch_count`
- `success_count`
- `failure_count`
- `skip_count`
- 每个 Patch 的文件拷贝数
- 每个失败 Patch 的异常原因

统计关系固定为：

- `success_count + failure_count = total_patch_count`
- `skip_count` 是 `failure_count` 的子类统计，不是并列主分类

## 7. 非范围契约

Tool1 当前不承诺以下能力：

- 点云拷贝
- 轨迹拷贝
- 字段重命名
- 坐标系转换
- 几何修复
- 图层内容分析
- 深度 manifest 治理
- 复杂业务逻辑判断

## 8. 后续实现注意事项

- 后续实现采用固定脚本，参数集中在文件头，不要求命令行参数驱动
- 当前固定脚本入口为 `scripts/t00_tool1_patch_directory_bootstrap.py`
- 文件名、日志文件命名和具体摘要格式可在编码阶段补足
- 具体异常分类可在编码阶段细化，但不得改变“异常 Patch 跳过并记失败、不中断全量”的语义
- 任何新增能力若触及非范围项，必须先更新规格文档并重新评审
