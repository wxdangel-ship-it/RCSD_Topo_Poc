# 12 术语表

- `T00`：`RCSD_Topo_Poc` 中的 Utility Toolbox / 工具集合模块
- `Tool1`：当前唯一纳入 T00 的 Patch 数据整理脚本
- `PatchID`：源 `vectors` 目录下一级子目录名，对应目标 Patch 目录名
- `源 Patch 矢量目录`：`D:\TestData\POC_Data\数据整理\vectors` 及其 WSL 映射路径
- `目标根目录`：`D:\TestData\POC_Data\patch_all` 及其 WSL 映射路径
- `skip_count`：因异常被跳过的 Patch 数，是 `failure_count` 的子类统计
- `failure_count`：执行失败的 Patch 总数，包含被跳过的异常 Patch
