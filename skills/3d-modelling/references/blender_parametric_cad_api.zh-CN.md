# Blender Parametric CAD：中文 API 使用参考

[English API contract](blender_parametric_cad_api.md) · [中文使用指南](../../../docs/guide.zh-CN.md)

适用于 0.18.1。本文按任务解释公开 API、单位和持久化规则；完整逐字段签名、
Blender 操作符及运行时字段列表集中维护在英文契约中，避免复制两套机器接口表。
API 名称、枚举值和 UUID 在两种语言中完全一致。MCP 仍提供
`cad://skill/3d-modelling` 与 `cad://api-reference` 资源。

## 单位、身份与状态

| 接口 | 长度 | 角度 |
| --- | --- | --- |
| 语义 MCP、Blender UI | mm | degree |
| 直接 Python 几何 API | m | radian |
| STL 导出 | mm | — |
| OBJ / PLY 导出 | m | — |

Part、Feature、SketchEntity、Assembly、Instance 都使用 UUID。引用时使用返回的 UUID，
不使用 Blender 对象名称、polygon/edge 索引。特征状态包括 `NOT_EVALUATED`、`OK`、
`ERROR`、`BLOCKED`、`SUPPRESSED`。失败时保留最后有效显示结果，下游阻塞。

## MCP 连接与执行

[使用指南](../../../docs/guide.zh-CN.md#通过-mcp-连接-ai-客户端)统一维护安装与连接配置。
客户端优先连接已有服务，没有服务时可启动一个可见 worker；设置
`BLENDER_CAD_AUTOSTART=0` 禁止自动启动。默认端口 9800，端点文件在系统临时目录。
只应向受信任客户端开放服务。

`blender_execute_python({"code": "..."})` 在连接的 Blender 主线程执行受信任 Python。
命名空间跨调用保留并预置 `bpy`，返回 stdout、stderr、末尾表达式 repr。
它有完整文件/进程权限；需要持久历史、统一单位和验证时，优先用语义 `cad_*`。

| 工具组 | 主要入口 |
| --- | --- |
| 文档/Part | `cad_status`、`cad_get_document`、`cad_create_part`、`cad_get_part_studio`、`cad_set_active_part`、`cad_delete_part` |
| 草图 | `cad_create_sketch`、`cad_sketch_add_line`、`cad_sketch_add_circle`、`cad_sketch_add_rectangle`、`cad_sketch_update_rectangle` |
| 原始几何/区域 | `cad_add_geometry`、`cad_update_geometry`、`cad_delete_geometry`、`cad_profile`、`cad_delete_region`、`cad_restore_region` |
| 尺寸/约束 | `cad_sketch_add/update/delete_dimension`、`cad_sketch_add/delete_constraint`（斜杠表示对应的独立工具） |
| 检查 | `cad_get_sketch`、`cad_get_feature`、`cad_get_history`、`cad_get_edges`、`cad_list_references`、`cad_inspect_geometry` |
| 特征 | `cad_create_extrude/revolve/transform/mirror/chamfer/fillet`、`cad_update_feature`、`cad_delete_feature`、`cad_suppress_feature`、`cad_rollback`、`cad_rebuild` |
| 装配 | `cad_create/list/get/update/delete_assembly`、`cad_add/update/remove_assembly_instance` |
| 输出 | `cad_validate_document`、`cad_export_part`、`cad_save_scene` |

表中的斜杠缩写不是实际工具名，完整名称和参数见英文契约。

## 草图建模流程

使用草图局部坐标和毫米。返回值包含稳定 UUID；几何/尺寸修改会求解、重建，并在失败时回滚。

```text
part = cad_create_part({"name": "Plate"})
sketch = cad_create_sketch({"part_id": part.part.id, "name": "Base", "plane": "XY"})
rect = cad_sketch_add_rectangle({"sketch_id": sketch.sketch.id,
                                "x_mm": 0, "y_mm": 0,
                                "width_mm": 80, "height_mm": 50})
plate = cad_create_extrude({"sketch_id": sketch.sketch.id,
                            "distance_mm": 20, "operation": "NEW", "depth_mode": "BLIND"})
# 矩形已拥有驱动宽高尺寸，不要重复创建。
cad_sketch_update_dimension({"sketch_id": sketch.sketch.id,
                             "dimension_id": rect.width_dimension_id, "value_mm": 100})
cad_get_history({"part_id": part.part.id})
```

`cad_sketch_add_line` 接受 `x1_mm/y1_mm/x2_mm/y2_mm`；圆接受
`cx_mm/cy_mm/diameter_mm` 或 `radius_mm`。矩形返回 `rectangle_id`、
四边 `entity_ids.bottom/right/top/left` 和驱动宽高尺寸 ID。
使用 `cad_sketch_update_rectangle` 改位置/宽高可保留四条线 UUID。

约束包括 `HORIZONTAL`、`VERTICAL`、`COINCIDENT`、`PARALLEL`、
`PERPENDICULAR`、`EQUAL`。实体引用使用 `entity_id` 和可选 `sub_element`；
重合支持线 `START`/`END` 和圆 `CENTER`，方向约束使用整条线，相等支持线/线或圆/圆。
尺寸包括 `LENGTH`、`HORIZONTAL_DISTANCE`、`VERTICAL_DISTANCE`、`DISTANCE`、
`RADIUS`、`DIAMETER`。求解返回 `SOLVED`、`CONFLICT` 或 `INVALID_REFERENCE`；
MCP 错误包括 `CONSTRAINT_CONFLICT` / `INVALID_REFERENCE`，不提交部分失败草图。

`cad_get_sketch` 返回局部实体、尺寸、约束、语义矩形、平面引用和状态；
`cad_get_history` 返回特征 UUID/类型/依赖/状态；`cad_inspect_geometry` 返回连接分量、
边界、流形性和体积。`cad_get_edges` / `cad_list_references` 返回持久引用，不返回运行时索引。

## 直接 Python：文档、Part 与重建

推荐先构建完整持久特征图，再保存并重建一次，避免模拟鼠标。

```python
import bpy
from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.sketch.sketch import SketchFeature
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.blender import adapter, environments

part = Part(name="Plate")
sketch = SketchFeature.on_plane("Base", "XY")
set_rectangle(sketch, 0, 0, .080, .050)
part.add_feature(sketch)
part.add_feature(ExtrudeFeature(sketch_id=sketch.id, distance=.020))
document = adapter.load_document()
document.add_part(part)
adapter.save_document(document)
result = adapter.rebuild_part(environments.part_studio_scene(), part.id)
assert result.success, [e.message for e in result.errors]
```

在 Blender 中启用插件；未启用时桥接会抛出带操作说明的 `CadDocumentError`。
不要在同一会话反复 `register()`。`CadDocument(parts=[], active_part_id=None,
schema_version=3, assemblies=[])` 提供 Part/Assembly/Instance 增查删和活动 Part 管理。
`Part(name=..., features=[], rollback_index=None)` 保存线性历史，`add_feature` 添加条目。
特征共有 UUID、名称、类型、dependencies、suppressed、状态和错误信息。

主要桥接函数为 `load_document()`、`save_document(document)`、
`rebuild_part(scene, part_id)`、`validate_cad_document(scene)` 和
`export_part(scene, part_id, filepath, file_format)`。名称含 `*_from_scene` /
`*_to_scene` 的旧读写函数仍兼容，但实际存储统一在 `CAD_DOCUMENT.json`。
`rename_part_geometry`、`remove_part_geometry` 和选择同步接口见英文契约。

## 草图数据、轮廓与吸附

`SketchLine`、`SketchCircle`、`SketchArc` 的直接 Python 坐标为米，圆弧角度为弧度。
`SketchFeature.on_plane(name, "XY", offset=...)` 建立基准支撑；
`on_feature_plane` / `on_face` 建立语义支撑。偏移保存在 `plane_reference.offset`，
不要把它烘焙到 origin；修改时用 `set_plane_offset()`。

数值函数集中在 `sketch.numeric`，包括 `set_rectangle`、`set_circle` 和形状编辑辅助函数。
尺寸与约束保存在草图中，`SketchSolver().solve(sketch)` 使用事务式投影求解，尽量保留
欠约束坐标，没有通用符号求解或自由度分析。

`ProfileDetector().detect(sketch)` 返回 success/profile/message。
`profile.iter_loops()` 返回离散闭合轮廓。圆、简单多边形、混合线弧、多闭合环和可拆分
边界受支持；开放、自交或不支持的分支轮廓会失败。删除区域记录由边界 UUID 派生的 region ID，
移除或替换几何后应清理失效的区域 ID。

`sketch.snapping` 的 `intersection_points`、`reference_points`、`snap_targets`、
`snap_point` 用于交点、端点/中心及曲线投影吸附，排除 construction 几何。

## 平面、面、轴与边引用

`SketchPlaneReference` / `PlaneReference` 支持 `DATUM`、`FEATURE_PLANE`、
`FACE` 和支持的 `DERIVED_PLANE`。基准面为 `XY/XZ/YZ`；特征支撑记录 producer UUID
与 role，面支撑还可包含源线 UUID。派生平面记录生产者局部签名和消歧提示。
`PlaneResolver().resolve(reference, context)` 或
`resolve_sketch_plane_from_history(part, sketch_id)` 返回 origin、x_axis、y_axis、normal。

`FaceReference` / 兼容 `TopoReference` 表示起止面、线侧面或 Revolve 端盖。
整周 Revolve 端盖还需要支持的 profile SketchLine UUID。
`AxisReference(reference_type="DATUM_AXIS", axis="Z", direction=1)` 表示基准轴；
`SKETCH_LINE` 需要 owning `sketch_id` 和 `entity_id`，`direction=-1` 反转轴。
`SelectionReference` 是非持久选择容器。

`EdgeReference` 保存生产者、角色、相邻平面、源实体提示与局部直线签名。
不要从 Blender edge 索引构造它。支持范围、容差和匹配顺序统一见
[架构与验证](../../../docs/development.zh-CN.md)。引用不唯一或消失时阻止下游，不猜测。

## 特征操作

| 类型 | 关键字段与限制 |
| --- | --- |
| `ExtrudeFeature` | `sketch_id`、米单位 `distance`、`direction`、`operation`、`depth_mode`；NEW/ADD 要求 BLIND，REMOVE 可用 BLIND/THROUGH_ALL；兼容旧 CUT |
| `RevolveFeature` | `sketch_id`、`axis_reference`、弧度 `angle`、NEW/ADD/REMOVE；角度大于 0 且不超过 2π，轴平行于草图平面；反转影响部分旋转 |
| `TransformFeature` | 米单位 `translation`、XYZ 弧度 `rotation`、前一 body 依赖；变换当前实体及后续参考坐标系，不产生第二个 Body |
| `MirrorFeature` | `source_feature_id`、`mirror_plane`、源和前一 body 的 dependencies；只支持较早的加法 Extrude/Revolve，镜像后 Boolean Add 仍须单连接、流形、非零体积 |
| `ChamferFeature` | 持久直边引用、等距离；不支持非对称倒角 |
| `FilletFeature` | 持久直边引用、固定半径；不支持可变半径或切向链 |

直接构建 Add/Remove 图时，`dependencies` 必须包含草图和前一个实体特征 UUID。
MCP 会维护所需依赖。Revolve 的普通轮廓边可以同时作为轴，仍保留在闭合轮廓中；
跨草图轴记录归属草图 UUID。退化或零体积旋转在替换有效显示前被拒绝。

`PartEvaluator(geometry_backend).evaluate(part)` 返回 `EvaluationResult`，包括
success、body、errors、context；错误包含 feature_id、feature_name、message。
`GeometryBackend` 是可替换内核接口，`BlenderMeshBackend` 为当前网格实现。
后端负责拉伸/旋转工具、Boolean、刚体变换、镜像和 provenance；不是精确 BRep 内核。

## 齿轮与指定运动

```python
from math import pi
from blender_parametric_cad.sketch.gears import spur_outline, internal_outline, rack_outline, add_outline
from blender_parametric_cad.blender.motion import set_planar_motion

# 直接 API：米/弧度；普通草图几何，不是专用齿轮特征。
add_outline(sketch, spur_outline(.002, 20, backlash=.00015))
# 将 internal_outline(.002, 80, backlash=.00015) 从齿圈毛坯中切除。
# rack_outline(.002, 24, backlash=.00015) 的节线为 Y=0。
set_planar_motion(instance_id, angle="2*pi*(frame-1)/240")
set_planar_motion(rack_instance_id, x=".04*sin(2*pi*(frame-1)/240)")
```

backlash 表示每个齿轮在节圆上的齿厚减薄量；两个外齿轮各减薄 0.15 mm，
名义总切向间隙为 0.30 mm。默认压力角 20°，零变位、圆弧齿根；不是滚刀精确包络。
外齿轮至少 18 齿，并检查给定压力角下的未覆盖欠切；内齿至少 40 齿且齿顶圆位于基圆外。
这些输入检查不能替代装配干涉或强度验证。

运动表达式是受信任的 Blender 原生驱动表达式。angle 为局部 Z 的 delta 弧度旋转，
x/y 为父坐标系中的 delta 米单位平移。四元数驱动和微小位移修正随保存保留。
不带表达式调用不改变运动。它不提供关节、接触力或自由度求解。

## 装配与输出

`cad_create_assembly` 新建，`cad_list_assemblies` 列表，`cad_get_assembly(assembly_id)`
检查；`cad_update_assembly` 改名，`cad_delete_assembly` 删除。
`cad_add_assembly_instance` 接受 assembly_id、part_studio_id（兼容 part_id）、可选名称、
translation_mm、rotation_deg、suppressed。更新/删除还需要 instance_id。
向量可用 `[x,y,z]` 或 `{x,y,z}`，XYZ 旋转顺序 `Rz @ Ry @ Rx`。
只更新平移时保留旋转，不向源 Part 追加 Transform。

返回值包含 ok、assembly_id、instance_id、part_studio_id、Assembly 检查结果；
每个实例列出矩阵、suppression、stale 和 diagnostic。无效修改/载体分配失败会恢复先前状态。
删除被引用源会返回 `PART_IN_USE` 和全部引用。

`export_part` 会重建指定 Part，只导出其结果并恢复选择，返回最终路径。
缺扩展名时补全；非法 Part/格式/路径或失败重建抛出 ValueError，导出器失败抛出 RuntimeError。
STL 已换算毫米，不要再乘以 1000。调用 `validate_cad_document` 检查依赖、轮廓来源、
特征状态和空结果；MCP 对应 `cad_validate_document`、`cad_export_part`、`cad_save_scene`。

## 序列化、UI 与运行时信息

`core.serialization` 提供 JSON 与字典转换。Schema v3 在同一文档中保存 Parts/Assemblies，
迁移保留 UUID，不保存网格索引。历史重建后生成的面/边候选和 provenance 缓存不是持久身份。

Blender `bpy.ops.parametric_cad.*` 操作符供原生 UI 使用，完整名称和 UI 字段集中在
[英文操作符契约](blender_parametric_cad_api.md#blender-operator-façade)。
绘图、拾取、Measure 等 modal 操作依赖 3D View，不建议 AI 模拟鼠标调用。
测量的毫米距离/坐标存于临时 UI，不创建特征或修改 JSON。
`blender.viewport.sketch_overlay`、`blender.viewport.provenance` 的预览、高亮、测量和重绘
辅助函数只影响显示，不应当作持久 CAD 数据。以 `_` 开头的函数是内部实现，不在公开 API 范围内。
