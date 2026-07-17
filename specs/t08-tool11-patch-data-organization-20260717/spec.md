# T08 Tool11 Patch 级数据整理规格

**Feature Branch**: `codex/t08-tool11-patch-data-organization`
**Created**: 2026-07-17
**Status**: Ready for implementation
**Input**: 将原始数据根目录下全部 Patch 的 SWSD、RCSD、FRCSD 整理到参数化目标根，并把指定 6 个实验 Patch 另行复制到独立实验根。

## 1. 目标与边界

Tool11 是 T08 正式 Patch 级数据整理工具。它只做可审计、逐字节保持的数据复制和目录归一，不转换格式、不重投影、不修改字段、几何或拓扑。

每个源 Patch 固定映射为：

```text
<source-root>/<PatchID>/SD_City/target_level1/**
  -> <output-root>/<PatchID>/SWSD/**

<source-root>/<PatchID>/SD_City/base_origin/**
  -> <output-root>/<PatchID>/RCSD/**

<source-root>/<PatchID>/rc_sw_gd_merge/RCSDNode.geojson
<source-root>/<PatchID>/rc_sw_gd_merge/RCSDRoad.geojson
<source-root>/<PatchID>/rc_sw_gd_merge/RCSDRoadNextRoad.geojson
  -> <output-root>/<PatchID>/FRCSD/
```

默认实验 Patch：

- `5524185996921171`
- `5724833136255764`
- `5524185996921755`
- `5724833136255765`
- `5724833136255763`
- `5524185996921337`

这些 Patch 必须物理复制到 `<experiment-output-root>/<PatchID>/<SWSD|RCSD|FRCSD>`，并与主整理成果逐文件一致。

## 2. 用户场景

### US1 - 全量 Patch 目录归一（P1）

作为数据准备人员，我提供原始根和目标根后，能够一次性把全部 Patch 整理成统一的 `SWSD / RCSD / FRCSD` 结构。

**Independent Test**: 构造多个 Patch 和嵌套 SWSD/RCSD 文件，执行 Tool11 后逐路径、逐字节核对主输出。

**Acceptance Scenarios**:

1. **Given** 两个合法 Patch，**When** 执行 Tool11，**Then** 两个 Patch 都出现在目标根且 SWSD/RCSD 内部结构完整保留。
2. **Given** `rc_sw_gd_merge` 含额外文件，**When** 执行 Tool11，**Then** FRCSD 只出现三个白名单 GeoJSON，额外文件只进入忽略审计。

### US2 - 实验 Patch 独立交付（P1）

作为实验人员，我需要在独立实验根中直接获得指定 6 个 Patch，而不从全量目录中再次手工筛选。

**Independent Test**: 源根包含默认 6 个实验 Patch 和至少 1 个非实验 Patch，执行后实验根只包含默认 6 个，且文件哈希与主输出相同。

**Acceptance Scenarios**:

1. **Given** 默认 6 个实验 Patch 均存在，**When** 执行 Tool11，**Then** 实验根只包含这 6 个 Patch。
2. **Given** 任一实验 Patch 不存在，**When** 执行 Tool11，**Then** 整批失败且两个正式输出根均不发布。

### US3 - 可追溯失败与安全覆盖（P1）

作为运行审计人员，我需要知道每个 Patch 的输入、输出、文件大小、SHA-256、失败原因、运行环境和性能，并确保失败不会留下半成品或破坏已有成果。

**Independent Test**: 分别制造缺目录、缺 FRCSD 文件、输出冲突和覆盖中失败，核对失败 summary、正式输出保护及临时目录清理。

**Acceptance Scenarios**:

1. **Given** 多个 Patch 各自存在不同缺失项，**When** 预检，**Then** summary 一次列出全部 Patch 错误并返回非 0。
2. **Given** 正式输出已存在且未传 `--overwrite`，**When** 执行，**Then** 已有输出不变并显式失败。
3. **Given** 传入 `--overwrite`，**When** 新成果全部复制和校验成功，**Then** 两个根整体替换；任何提交前失败均保留旧成果。

## 3. 五类职责视角

### 产品

- 用三个根目录参数完成全量整理和实验子集交付。
- 默认实验 Patch 固化为用户确认的 6 个 ID，同时允许通过重复参数显式替换该列表。
- 主输出与实验输出均保持消费者期望的原文件名和内部目录。
- 为已确认的内网目录提供 WSL 一键运行入口，避免人工重复录入中文 Windows 路径。

### 架构

- 正式入口由通用 Python 核心入口 `scripts/t08_tool11_patch_data_organization.py` 和固定场景 WSL 封装入口 `scripts/t08_tool11_run_innernet.sh` 组成。
- 核心逻辑位于 T08 callable；Python 脚本负责参数解析、进度和退出码，WSL 封装只负责默认路径、路径转换、固定实验 Patch、日志和调用核心入口。
- Tool11 被正式登记为 T08 第三个命名特例：业务复制文件保持原名，summary 文件名仍以 `_tool11` 结尾。
- 两个输出根采用同轮暂存、校验、发布和覆盖回滚，不发布部分成功目录。

### 研发

- 只使用 Python 标准库，不新增依赖。
- SWSD/RCSD 递归复制普通文件并保留空目录；FRCSD 只复制三个根级白名单文件。
- 复制后独立计算源、主输出和实验输出 SHA-256；不以文件大小相同替代内容校验。
- 源根、主输出根、实验输出根必须互不包含，禁止递归复制自身。

### 测试

- 使用临时目录构造合成 Patch，不依赖内网数据。
- 覆盖默认 6 Patch 实验集、嵌套目录、空目录、FRCSD 白名单、缺失项聚合、冲突保护、显式覆盖、CLI 参数、WSL 封装和 summary。
- 运行 T08 全量测试，证明 Tool1-10 不回退。

### QA

- CRS：不解析、不转换；通过字节一致性证明 CRS 载荷未改变。
- 拓扑：不执行任何拓扑或几何运算，`silent_fix_applied=false`。
- 几何语义：业务文件逐字节复制，源与两个目标 SHA-256 一致。
- 审计：记录输入、参数、Patch、相对路径、大小、哈希、忽略项、错误、环境和输出。
- 性能：记录扫描、复制校验、发布、总耗时以及 bytes/s、MiB/s。

## 4. 功能需求

- **FR-001**：Tool11 MUST 扫描 `source-root` 下所有名称为数字的直接子目录作为 Patch，并按 PatchID 排序。
- **FR-002**：非 Patch 文件和非数字目录 MUST NOT 被复制，MUST 写入根级忽略审计。
- **FR-003**：每个 Patch MUST 存在 `SD_City/target_level1`、`SD_City/base_origin` 和 `rc_sw_gd_merge`。
- **FR-004**：SWSD MUST 递归全量复制 `target_level1`，保留相对目录、文件名、内容和空目录。
- **FR-005**：RCSD MUST 递归全量复制 `base_origin`，保留相对目录、文件名、内容和空目录。
- **FR-006**：FRCSD MUST 只复制根级 `RCSDNode.geojson / RCSDRoad.geojson / RCSDRoadNextRoad.geojson`。
- **FR-007**：缺少任一必需目录或 FRCSD 文件时 MUST 检查完其余 Patch，再整批失败。
- **FR-008**：默认实验列表 MUST 是用户指定的 6 个 Patch；重复 `--experiment-patch-id` MUST 整体替换默认列表。
- **FR-009**：所有实验 Patch MUST 同时存在于本轮主 Patch 集；缺失时整批失败。
- **FR-010**：实验根 MUST 只包含实验列表中的 Patch，目录结构与主输出一致。
- **FR-011**：源、主输出和实验输出 MUST 是互不重叠的目录树；相同路径或父子包含关系 MUST 失败。
- **FR-012**：默认 MUST 拒绝已存在的主输出根或实验输出根。
- **FR-013**：`--overwrite` MUST 仅在新主输出和实验输出均完成复制与哈希校验后替换旧根；失败 MUST 回滚或保留旧根。
- **FR-014**：Tool11 MUST 拒绝源树中的符号链接和特殊文件，避免复制语义或边界不明确。
- **FR-015**：每个复制文件 MUST 记录源大小、源 SHA-256、主输出 SHA-256；实验 Patch 还 MUST 记录实验输出 SHA-256。
- **FR-016**：所有记录的哈希 MUST 一致；任何不一致 MUST 阻止正式输出发布。
- **FR-017**：成功和业务失败 MUST 生成文件名以 `_tool11.json` 结尾的 summary；未显式指定时使用唯一时间戳文件名并写在主输出根同级目录。
- **FR-018**：summary MUST 记录状态、错误、输入输出、参数、逐 Patch/逐文件审计、GIS 不变性、计数、环境和性能。
- **FR-019**：脚本 MUST 输出可定位进度；成功返回 `0`，输入或业务失败返回 `2`。
- **FR-020**：通用 Python 入口的所有业务路径 MUST 由参数提供；固定场景 WSL 封装 MAY 使用用户已确认的三个内网路径作为可覆盖默认值。
- **FR-021**：业务复制文件保留原名，作为 Tool11 已批准命名特例；summary 仍遵循 `_tool11` 命名。
- **FR-022**：Tool11 MUST NOT 修改源目录中的任何文件或目录。
- **FR-023**：固定场景 WSL 封装 MUST 自动转换 Windows 路径、显式传入 6 个实验 Patch、调用通用 Python 入口、保留退出码与持久日志，并默认拒绝覆盖。

## 5. 边界情况

- 源根不存在、没有数字 Patch 子目录或实验列表为空：失败并生成 summary。
- SWSD/RCSD 目录为空：允许，空目录必须出现在输出并被审计。
- SWSD/RCSD 含符号链接、FIFO、设备或其它特殊条目：失败，不跟随、不跳过。
- FRCSD 白名单名称只在子目录出现：视为缺失；只接受 `rc_sw_gd_merge` 根级精确文件。
- 输出父目录不存在：允许创建父目录，但不得创建或修改源根。
- 主输出或实验输出在复制期间失败：不发布暂存成果；已有正式根不变。
- 两个输出根位于不同卷：分别在各自父目录暂存，完成全部校验后再进入可回滚发布阶段。

## 6. 成功标准

- **SC-001**：合成全量数据中，主输出 Patch 集与源数字 Patch 集完全一致。
- **SC-002**：每个 Patch 的 SWSD/RCSD 相对文件和空目录集合完全一致，FRCSD 文件集合精确等于三个白名单文件。
- **SC-003**：实验根 Patch 集精确等于默认或显式实验列表，且每个实验文件与主输出哈希一致。
- **SC-004**：summary 中所有 `source/main/experiment` SHA-256 校验通过，文件和字节计数守恒。
- **SC-005**：所有预检/复制失败不产生半成品正式根；覆盖失败不改变已有根。
- **SC-006**：Tool11 聚焦测试、T08 全量测试、入口帮助、入口登记、文件体量和 `git diff --check` 全部通过。
- **SC-007**：固定场景 WSL 封装通过 shell 语法、默认值契约和临时目录端到端测试；二次运行在未授权覆盖时失败且保留既有成果。

## 7. 本轮不做

- 不执行 GeoJSON/GPKG 格式转换、CRS 解析或重投影。
- 不合并、裁剪、修复、重命名任何业务数据文件。
- 不把 Tool11 串入 T10 v1 Case runner 或全量总控。
- 不修改 T00、T01-T07、T09-T11 的业务接口。
- 不新增 repo CLI 子命令、Makefile 目标或第三方依赖。
