# 架构与验证

[首页](../README.zh-CN.md) · [English](development.md) | 简体中文

本文将原 M6、M7、M8、M11A 的实现说明合并为当前 0.18.1 的架构文档。
下列开发阶段的测试数量属于历史记录，不表示每次文档/视频修改都重新执行了所有测试。

## 文档归属与历史

不依赖 Blender 的 `CadDocument`、`Part`、`Feature`、`Assembly`、`AssemblyInstance`
保存持久状态。每个 Part Studio 拥有一条有序的单实体特征历史。Assembly 引用 Part，
不复制历史，本身也不接受单连接实体检查。

Schema v3 将唯一文档存储在带 fake user 的 Text 数据块 `CAD_DOCUMENT.json`。
主要接口为 `adapter.load_document()` / `save_document()`；名称含 Scene 的旧接口
仍作为兼容包装。JSON 使用较短的缩进行，避免 Blender Text 在兆字节长单行上的
二次复杂度插入成本。

迁移深拷贝旧数据、保留 UUID 和语义引用，并为 v2 添加 `assemblies: []`。
缺少 canonical Text 时扫描全部 Scene；多个非空旧文档不一致时，抛出
`MIGRATION_CONFLICT` 且不修改它们。迁移成功后清除可写 Scene 副本；空的活动 Scene
不能覆盖已有非空模型。

求值遵循依赖、抑制和回滚。失败特征为 `ERROR`，依赖它的特征为 `BLOCKED`，
最后有效网格仍显示。生成网格是临时结果，UUID 和历史才是持久契约；外部修改网格或
添加修改器不属于该契约。

## 持久平面引用

`PlaneReference` / `SketchPlaneReference` 保存基准、特征平面、语义面或支持的派生平面
身份，以及米单位偏移。`FaceReference` 由生产特征、角色和可选源 SketchLine UUID 标识。
兼容别名和旧扁平字段仍可读取；Blender polygon 索引不序列化。

求值建立语义平面。Extrude 提供起止平面和 SketchLine 侧平面；Through All 只提供侧平面，
因为端盖依赖运行时边界。部分 Revolve 提供源 `START_CAP` 和参数化旋转的 `END_CAP`。
整周 Revolve 仅在直线轮廓垂直于旋转轴时提供圆盘/圆环端盖，由源线 UUID 区分；
曲面侧壁仍不支持作为草图支撑。

运行时匹配先验证精确 provenance，再按稳定历史顺序匹配语义平面。多边形法线必须平行或
反平行，所有顶点都必须落在平面上。分裂端面共享规范化 `END_PLANE` 支撑；无精确
provenance 的重合生产者优先选择历史中较早者。匹配使用网格局部坐标，显示变换只用于
高亮，不作为 polygon 身份保存。

Transform 同时更新原点和完整坐标轴。Mirror 使用自身生产 UUID 与源角色/线 UUID，
派生支持的加法 Extrude/Revolve 引用；反射后反转 Y 保持右手系。后续 Transform
继续传播坐标系，无需将下游草图坐标烘焙为世界坐标。

Boolean 生成且无法匹配既有语义面的平面区域使用 `DERIVED_PLANE`：生产者 UUID、
规范化的生产者局部法线/偏移、源特征提示，以及可选质心/面积 `RegionHint`。
相连的共面分裂/三角化多边形组成一个候选，已有语义面优先。匹配顺序为精确 provenance
→ 语义平面 → 派生平面。提示必须唯一确定候选，否则返回 `MISSING` / `AMBIGUOUS`，
阻止下游草图，而不是猜测。

悬停、选择和新建草图共用重建后的运行时缓存。支持的面选择保存语义引用，并按完整坐标系
对齐正交视图，包含倾斜平面；不支持的面会明确提示。缓存随求值/重开恢复，不保存到
JSON 或自定义属性。匹配复杂度为 O(多边形数 × 语义平面数)，不是通用几何/拓扑修复。

## 持久直边与边特征

`EdgeReference` 保存生产者 UUID、角色（`PLANAR_INTERSECTION` / `PLANAR_BOUNDARY`）、
最多两个相邻平面、源实体提示，以及生产者局部 `EdgeSignature`。签名规范化方向与无限直线
上距原点最近的点；反转端点不会改变身份。中点和长度仅用于消歧，不能单独充当身份。

匹配先尝试精确 provenance，再尝试相邻平面/源实体，无相邻平面时使用局部直线签名。
不猜测缺失或歧义匹配。支持 Extrude 周边/竖边、平面/平面 Boolean 边、支持的部分 Revolve
端盖边界，以及可解析的 Transform/Mirror 直边。不支持同一平面内的细分边、曲边、切向链，
以及由 Fillet 新生成的下游边身份。

Select Edges 支持悬停/点击、Shift 添加、Enter 确认、Esc 取消。临时选择保存语义 JSON，
不保存运行时 edge 索引。`ChamferFeature` 使用等距离，`FilletFeature` 使用固定半径；
后端对临时 BMesh bevel，分别使用 1/8 段。二者都参与依赖、编辑、重建、抑制、回滚、
级联删除和重开；失败时保留最后有效结果。

### 集中管理的容差

| 匹配量 | 默认值 |
| --- | ---: |
| 平面法线 | `1e-6` |
| 平面绝对距离 | `1e-7 m` |
| 平面尺寸相对距离 | `1e-8` |
| 派生平面质心 | `1e-6 m`，相对 `1e-5` |
| 派生平面面积 | 相对 `1e-5` |
| 边方向 | `1e-6` |
| 边直线距离 | `1e-7 m`，相对 `1e-6` |
| 边中点 | `1e-6 m`，相对 `1e-5` |
| 边长度 | `1e-7 m`，相对 `1e-5` |
| 边端点 | `1e-6 m`，相对 `1e-5` |
| 整周 Revolve 角度 | `1e-9 rad` |

数值集中在 `PlaneMatchTolerance` 和 `EdgeMatchTolerance`，没有另外引入每个特征自己的边容差。

## 链接装配实现

每个 `AssemblyInstance` 有独立 UUID、源 Part UUID、名称、抑制状态和刚体 4×4 矩阵。
矩阵要求正旋转，不允许缩放或剪切。UI/MCP 使用毫米/度；内核使用米和旋转矩阵，
XYZ 输入组合顺序为 `Rz @ Ry @ Rx`。

稳定的 `CAD_PART_<uuid>` 源集合位于带 fake user 的 `CAD_SOURCE_ROOT` 下。
重建保留结果 Object、替换 Mesh、保留材质槽并更新 provenance 缓存，删除无用户的旧 Mesh。
源 Object/集合保持单位矩阵/零 offset。每个显示实例是在 `CAD_ASSEMBLY_<uuid>` 中
引用源集合的 Empty，并用 Part/Assembly/Instance UUID 标识，不复制源网格。
抑制只移除载体，保留持久 UUID。

重建源只更新共享几何，不写实例位姿；失败时标记源/载体 stale，并解释当前显示的是最后
有效几何。同步时分别赋值基础位置、四元数和缩放，避免将动画 delta 烘焙到 `matrix_world`。
原生平面运动接口使用四元数驱动通道，并清除默认 F-curve 映射键，防止微小的米单位正位移
被吸附到零。不带运动表达式的静止接口调用是有效的无操作。

Scene 角色为 `PART_STUDIO` / `ASSEMBLY`，不依赖名称。各 Scene 链接自身活动源/装配集合，
不全局隐藏视口。优先复用已有主窗口，后台和 load handler 不创建 GUI 窗口。
Assembly 选择不修改源草图/特征编辑状态；Edit Source Part 跳转到已有源窗口，
没有源窗口时才切换当前窗口。工具栏按窗口上下文提供条目，Assembly 中禁用草图面/边拾取。

删除被引用源时，`PART_IN_USE` 返回全部引用。删除装配只删除其自有集合/载体，不删除源。
`commit_assembly()` 先验证并分配缺失载体，再提交；分配失败会清理新增对象并恢复旧文档/
显示，不销毁已有载体。MCP worker 的 authoring Scene 固定解析为 Part Studio，
与当前窗口无关，复用进程内同一服务。文件加载会清除 timer，因此持久 load handler
会重新启用服务。

## 验证证据

| 范围 | 记录的覆盖 |
| --- | --- |
| M6/M6.2 | 历史 91 项 Python 测试；真实 Extrude/Revolve 端盖拾取、倾斜坐标系、Boolean 分裂、Transform/Mirror、重开 |
| M8.1 | 历史 96 项回归；真实 Chamfer/Fillet、多边重建、Boolean 边、缺失/歧义、清理、独立进程重开 |
| M11A | Python 3.9.6/3.13.9 历史各 124 项；真实共享实例几何、迁移、GUI 窗口和 socket 传输 |
| 0.18.1 齿轮流程 | 41 项针对性 Python 检查；STL 毫米尺寸、材质、微小运动、同步、源重建与保存重开 |
| 机构示例 | 25 个流形正体积网格；14 场景 × 73 采样；实际世界变换、闭合/干涉和 STL 尺寸 |
| 宣传视频 | 真实 8→12 mm 重建；各语言生成报告记录完整音视频解码和字幕时间检查 |

历史 M6 检查包含 120° 圆台、分裂端盖共享支撑、整周端盖选择、轴反转与重开缓存。
M8.1 没有单独自动化指针级 Shift 点击，但验证过原生悬停/单选和真实多边重建路径。

M11A 使用 A=80×50×20 mm、B=20×10×30 mm，B 实例位于 ±50 mm，其中一个转 180°。
通过 evaluated 世界边界验证单一共享 B 源、20→35→40 mm 改宽、稳定 UUID/位姿、
stale/错误恢复、抑制、源删除保护和分配回滚。两个真实 GUI 窗口验证 20→35→42 mm
编辑、独立工具栏、源跳转和窗口复用。当前迁移脚本统一生成临时 v2 fixture；
早期实测使用的 ZipString 样本已删除。迁移冲突仍保持非破坏性。GUI 证据来自 macOS，
不是 Windows/Linux 桌面验收。

机构采样不是连续碰撞证明或承载试验。[机构文档](../examples/mechanisms/README.zh-CN.md)
列出了允许接触和未提供的支撑。报告记录实际检查，历史测试数量不代表通用覆盖保证。

## 复现选定检查

测试导入 `blender_parametric_cad`，因此克隆时使用该可导入目录名。
在仓库根目录执行，确保父目录位于 Python 导入路径：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .. -q
blender --background --factory-startup --python-exit-code 1 --python tests/blender_gear_workflow_validation.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_m11a_validation.py
blender --factory-startup --python-exit-code 1 --python tests/blender_m11a_gui_validation.py
BLENDER_CAD_GPU_BACKEND=metal python3 tests/m11a_mcp_transport_validation.py
```

第一条执行完整 Python 套件，针对小改动可指定单独测试模块。GUI 脚本会打开真实窗口；
GPU 参数必须符合本机构建。其余阶段专用脚本保留在 `tests/`，本次文档合并未删除它们。

实现按 `core/`、`sketch/`、`features/`、`geometry/`、`blender/`、`mcp/` 组织。
[完整 API 参考](../skills/3d-modelling/references/blender_parametric_cad_api.md)保持原 MCP 资源路径。
原四份阶段文档可在 [v0.18.1 Git 历史](https://github.com/wyp41/blender-parametric-cad/tree/v0.18.1)
查看原始逐次运行记录。
