# 12 术语表

- `working layers`：模块开始阶段从 raw Nodes / Roads 复制得到的运行期工作图层。
- `roundabout preprocessing`：在 Step1 前，把环岛 roads 聚合成单一路口语义节点的预处理阶段。
- `endpoint pool`：逐轮 staged runner 传递的全量 `seed / terminate` 端点池，不要求上一轮必须 validated。
- `hard-stop`：端点仍可作为 seed / terminate，但不能被当作 through node 穿越。
- `segment_body`：某个 validated pair 的 pair-specific road body，不等于所有相关 road。
- `trunk`：支撑 pair 成立的最小闭环或主骨架 road 集。
