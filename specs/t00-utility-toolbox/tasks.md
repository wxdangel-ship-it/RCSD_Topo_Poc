# T00 Utility Toolbox 任务清单

## 1. 本轮编码任务

- [x] 盘点现有 T00 / Tool1 / Tool2 结构与脚本入口
- [x] 修正 Tool2 为 per-patch `DriveZone_fix.geojson` + 根目录全局 `DriveZone.geojson`
- [x] 新增 Tool4：`A200_road_patch.geojson`
- [x] 新增 Tool4 unmatched 输出：`A200_road_patch_unmatched.geojson`
- [x] 新增 Tool5：`A200_road_patch_kind.geojson`
- [x] 新增 Tool6：`nodes.geojson`
- [x] 新增 Tool7：目录级 `.geojson` 批量转 `.gpkg`
- [x] 为 Tool2 / Tool4 / Tool5 补共享 CRS、字段兼容、摘要写出和进度打印能力
- [x] 更新 `README / AGENTS / INTERFACE_CONTRACT`
- [x] 更新 `spec / plan / tasks`
- [x] 更新 T00 architecture 与入口注册表中的最小必要源事实
- [x] 增加定向测试并做语法 / 单测验证

## 2. 内网验证前任务

- [ ] 在真实 `D:\TestData\POC_Data\patch_all` 路径运行 Tool2
- [ ] 在真实 `D:\TestData\POC_Data\first_layer_road_net_v0` / `v1_patch` 路径运行 Tool4
- [ ] 在真实 `D:\TestData\POC_Data\first_layer_road_net_v0` 路径运行 Tool5
- [ ] 在真实目录路径运行 Tool6
- [ ] 在真实目录路径运行 Tool7
- [ ] 复核 Tool2 per-patch fix 输出数量与摘要一致
- [ ] 复核 Tool4 unmatched / conflict 统计
- [ ] 复核 Tool5 `kind` 拆分、去重、重组是否符合规则

## 3. 推荐执行顺序

1. Tool2
2. Tool4
3. Tool5
4. Tool6
5. Tool7

## 4. 本轮不做

- [x] 不返工 Tool1 业务逻辑
- [x] 不重写 Tool3
- [x] 不扩展 Tool8+
- [x] 不新增重型框架
- [x] 不引入复杂 manifest / 数据库治理
- [x] 不修改与 T00 无关的业务模块
