# M11A — Linked Part Studio / Assembly 实现与验证

版本：0.18.0。分支：`feature/m11a-linked-assemblies`。未合并分支。
验证日期：2026-10-23（Asia/Taipei）。使用本机真实 Blender 5.1.2 / Python 3.13.9。

## 实现

1. **核心模型**：`core/assembly.py` 提供 Blender 无关的 `Assembly` 和
   `AssemblyInstance` dataclass。实例保存独立 UUID、名称、源 Part UUID、刚体
   4×4 矩阵和 suppression。`CadDocument` 增加 Assembly/Instance 的增查删方法。
   Feature History 仍只属于源 Part；Assembly 不经过单连接体检查。
2. **Schema v3**：v1 保留既有平面迁移逻辑，v2 添加 `assemblies: []`。
   迁移使用深拷贝，保留 Part、Feature、Sketch、Rectangle、Dimension、Constraint
   UUID 以及面/边引用。既有 JSON 接口仍可用。
3. **唯一持久化存储**：`adapter.load_document()` / `save_document()` 使用
   `bpy.data.texts["CAD_DOCUMENT.json"]`，并设置 fake user。原有
   `load_document_from_scene(scene)` / `save_document_to_scene(scene, document)`
   保留为兼容包装。成功迁移后清空所有 Scene 上的旧 JSON，避免两份可写数据。
   没有 canonical Text 时扫描全部 Scene，而不是只看当前 Scene；多个非空文档
   不一致时抛出 `MIGRATION_CONFLICT`，不修改原数据。
4. **源集合**：fake-user `CAD_SOURCE_ROOT` 下，每个 Part UUID 拥有一个稳定
   `CAD_PART_<uuid>` 集合，以 `cad_source_collection` / `cad_part_id` 标识。
   重建保留结果 Object，替换其 Mesh，并检查旧 Mesh users 后删除。面/边 provenance
   缓存继续刷新。集合 offset 和源 Object 矩阵为零/单位矩阵，避免位姿重复应用。
5. **实例集合**：每个 Assembly UUID 拥有一个 `CAD_ASSEMBLY_<uuid>` 集合。
   每个未抑制实例对应一个 Empty，其 `instance_collection` 指向原源集合，
   不复制源 Mesh。载体以 `cad_instance_id`、`cad_assembly_id`、`cad_part_id`
   标识。未显示的 Assembly 集合也由 fake user 保留。抑制保留模型 UUID，移除载体。
6. **自动更新**：普通 `rebuild_part()` 替换共享源 Mesh 后，所有 Collection
   instances 直接显示新几何，并重绘全部窗口。源重建不写入任何实例位姿。
   失败重建保留最后有效 Mesh，设置源/载体 stale 标志，并在 Assembly 面板和 MCP
   检查结果中给出 last-valid-geometry 诊断。
7. **Scene / 窗口隔离**：`cad_scene_role` 使用 `PART_STUDIO` / `ASSEMBLY`，
   不依赖 Scene 名称。Part Studio 只链接当前源集合；其他源仍存于源根集合。
   新文件创建专用 Part Studio Scene；旧文件复用拥有旧生成对象的 Scene。
   Assembly Scene 只链接选中 Assembly 的实例集合。没有全局 hide_viewport 操作。
   `open_assembly_window` / `open_part_studio_window` 复用已有窗口，必要时使用
   `wm.window_new_main()`；后台不创建 GUI 窗口，load handler 也不开新窗口。
8. **选择 / 工具栏**：Assembly 选择仅设置其 Scene 的 `active_assembly_id` / 
   `selected_instance_id`，不更改文档 active Part、源 Sketch 或 Feature 状态。
   源对象选择仍沿用已有 Part / Feature 同步。面/边拾取和 Sketch overlay 在
   Assembly 中停用。工具栏改用 Blender 原生动态条目，按各窗口的 Scene / mode
   显示，避免一个窗口全局注销另一个窗口所需的工具。
9. **Edit Source Part**：由 Instance UUID 解析原 Part UUID，更新 Part Studio
   Scene 的 active Part，复用已有源窗口；已有源窗口时不切走 Assembly 窗口。
   若没有源窗口，切换当前窗口到源 Scene。保留 Assembly 选择及实例位姿；源已激活时
   不重复重置其编辑状态。
10. **GUI**：提供 Assembly 新建、选择、重命名、删除；实例添加、选择、删除、
    Edit Source、名称/suppression 和六个数值位姿字段。GUI 使用 mm / degrees；
    持久数据使用 meters / radians 对应的矩阵，旋转顺序为 `Rz @ Ry @ Rx`。
11. **删除和事务**：源 Part 被任一实例引用时，核心统一抛出 `PART_IN_USE`，
    包含全部引用 Assembly/Instance UUID，GUI/MCP 共用此规则。删除 Assembly
    仅删除其载体和拥有的集合。创建实例先分配全部缺失载体，失败时清理新增载体；
    `commit_assembly()` 验证后提交，异常则恢复前一文档和显示。现有载体不因分配失败而
    被销毁。载体使用 quaternion storage，避免 180° Euler 舍入引发重复求值位姿变化。
12. **MCP 路由**：文档读取与当前窗口无关；worker 的 `scene` 固定解析 Part Studio
    Scene，保留旧的 active-Part fallback。整个 Blender 进程仍使用单一现有服务。
    `cad_get_document` 保留既有返回字段并加入 assemblies。

## MCP 工具及示例

新增：`cad_create_assembly`、`cad_list_assemblies`、`cad_get_assembly`、
`cad_add_assembly_instance`、`cad_update_assembly_instance`、
`cad_remove_assembly_instance`。另提供 `cad_update_assembly` 和
`cad_delete_assembly` 与 GUI 组织操作对应。

```text
cad_create_assembly({"name": "Guides"})
cad_add_assembly_instance({
  "assembly_id": "<returned assembly UUID>",
  "part_studio_id": "<existing Guide Part UUID>",
  "name": "Guide Left", "translation_mm": [-50, 0, 0]
})
cad_add_assembly_instance({
  "assembly_id": "<same assembly UUID>",
  "part_studio_id": "<same Guide Part UUID>",
  "name": "Guide Right", "translation_mm": [50, 0, 0], "rotation_deg": [0, 0, 180]
})
cad_get_assembly({"assembly_id": "<same assembly UUID>"})
```

`part_id` 是 `part_studio_id` 的兼容别名。位姿输入同时接受三元素数组和 x/y/z 对象。
Add/update 返回 `ok`、`assembly_id`、`instance_id`、`part_studio_id` 和 Assembly
检查结果。检查结果包含源引用、矩阵、suppression、stale 和诊断。
完整参数见 `skills/3d-modelling/references/blender_parametric_cad_api.md`。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 纯 Python 回归 + `test_assembly.py` | 系统 Python 3.9.6 与 Blender Python 3.13.9 各 124 项通过 |
| M3 历史、回滚、suppression、重建幂等、保存重开 | 通过 |
| M3.5 Part Studio 管理、切换、cascade delete | 通过 |
| M3.6 P0 单连接体验证 | 通过 |
| M4 持久面引用与保存重开 | 通过 |
| M8.1 Chamfer / Fillet / 多边 / Transform / Boolean 边 / cleanup | 通过 |
| M8.1 新进程重开验证 | 通过 |
| M9 驱动尺寸及下游 Chamfer | 通过 |
| M9 新进程重开验证 | 通过 |
| M9C MCP Sketch/约束/尺寸/Through All/Chamfer/检查 | 通过 |
| M9C 新进程重开验证 | 通过 |
| M11A 真实源 / Collection Instance 几何 | 通过 |
| M11A 两个真实 GUI 主窗口 | 通过 |
| M11A 真实 socket / JSON-RPC / public MCP 工具 | 通过 |

M11A 几何测试创建 A=80×50×20 mm、B=20×10×30 mm，一个 Assembly 含 A/B1/B2。
B1 位于 −50 mm，B2 位于 +50 mm 且绕 Z 旋转 180°。通过实际 evaluated depsgraph
检查实例世界坐标 bounds，验证源原点/集合 offset、只有一个 B 结果 Object、两个 B
载体共享集合、Assembly 无额外 raw source objects，以及 width 20→35 mm 后两实例更新。
A 的 Mesh 数据、B Object/集合身份、实例 UUID/载体身份与位姿均保持。还验证失败源
重建 stale、重复同步无重复对象、抑制/恢复/删除、源删除保护、无效输入及载体分配失败
的事务恢复、从 Assembly 激活上下文导出非活动 Part。

保存/重开测试验证一个 canonical 文档、两个 Part 历史、一个 Assembly、三个实例的
UUID/引用/位姿；重开后再改 width 35→40 mm，链接仍更新。使用现有
`zipstring_cad_mcp_3part.blend` 验证 v2 自动迁移，只将迁移结果另存临时文件；
原文件 SHA-256 保持不变。该历史项目现已清理，当前脚本统一生成临时 v2
Scene-storage fixture，不再依赖仓库外样本。额外验证冲突的旧 Scene 文档不被覆盖，空的活动 Scene
不替换已有非空模型。

双窗口测试实际调用 `wm.window_new_main()`，在 Blender GUI 事件循环中用普通
`apply_dimension` 操作编辑尺寸（20→35→42 mm），在另一真实窗口选择实例并调用
Edit Source Part；窗口状态与共享几何均通过断言。不是 mocked Window。工具栏
通过各窗口的实际 `tools_from_context()` 检查 Assembly 不暴露 CAD Sketch 工具。
截图和 JSON 记录输出到系统临时目录：`cad_m11a_part_window.png`、
`cad_m11a_assembly_window.png`、`cad_m11a_gui_result.json`。

复现入口：

```sh
PYTHONPYCACHEPREFIX=/tmp/cad-pycache python3 -m unittest discover -s tests -t .. -q
blender --background --factory-startup --python-exit-code 1 --python tests/blender_m11a_validation.py
blender --factory-startup --python-exit-code 1 --python tests/blender_m11a_gui_validation.py
BLENDER_CAD_GPU_BACKEND=metal python3 tests/m11a_mcp_transport_validation.py
```

## 发现及修复的问题

- Scene 级 JSON 会使活动 Assembly Scene 被误认为新文档：改为唯一 Text 存储。
- DISPLAY 集合和按活动窗口路由会混淆源 / 实例：改为 UUID 集合及固定 authoring Scene。
- 全局切换工具栏注册会影响另一个窗口：改为窗口上下文动态工具列表。
- 非活动源 Part 不在当前 Scene 中导致选择式导出失败：临时链接到 authoring Scene，
  在明确的 Scene/ViewLayer override 中导出并恢复原选择/链接。
- 重复写入 180° Euler 位姿会产生浮点变化：载体改用四元数，并避免写回相同矩阵。
- Part 删除改变动态枚举索引后可能读取到无效 UI 值：保存前捕获原 UUID，再按 UUID
  更新 Part UI；Assembly 删除也保存并恢复有效的选择。
- 旧 M4 脚本将当前语义平面结果断言成 `END_FACE`；旧 M9C 脚本为已拥有自动尺寸的
  rectangle 重复添加驱动尺寸。两项均在原始 main 快照复现，已更新旧脚本的断言/
  数据准备；没有修改对应几何算法或 solver 来绕过测试。
- 原有序列化检查脚本读取 Scene JSON、旧 schema 测试期待 v2：同步到 canonical
  Text / schema v3；保持原检查目的。

## 已知限制

- 仅实现扁平 Assembly 实例列表；不实现 mates、joints、嵌套 Assembly、Assembly
  Boolean、运动学、碰撞约束、多体 Part Studio、STEP 或其他 CAD 引擎。
- 已有窗口会被复用和更新；没有额外实现跨平台 OS 窗口前台焦点控制。
- GUI 验收由真实 Blender 窗口中的原生操作驱动；未进行人工鼠标操作或 Windows/Linux
  桌面环境验收。
- 本机 Blender 构建只提供 Metal，沙箱内还会在启动阶段崩溃；实际验证在沙箱外运行。
  真实 headless socket 测试显式设置 `BLENDER_CAD_GPU_BACKEND=metal`。
  既有 MCP macOS headless 默认选择 OpenGL 的策略未在本里程碑重写。
- 未向用户的已安装扩展目录部署，也未改写原模型文件；提供安装 ZIP 和源码分支。

## 精确改动文件

- `M11A_LINKED_ASSEMBLIES.md`
- `README.md`
- `__init__.py`
- `blender/adapter.py`
- `blender/environments.py`
- `blender/operators/assembly.py`
- `blender/operators/part.py`
- `blender/operators/selection.py`
- `blender/properties.py`
- `blender/ui/panels.py`
- `blender/ui/tools.py`
- `blender/viewport/sketch_overlay.py`
- `blender_manifest.toml`
- `core/assembly.py`
- `core/document.py`
- `core/serialization.py`
- `mcp/blender_worker.py`
- `mcp/protocol.py`
- `mcp/server.py`
- `skills/3d-modelling/references/blender_parametric_cad_api.md`
- `tests/blender_headless_m4_validation.py`
- `tests/blender_headless_m8_1_validation.py`
- `tests/blender_headless_validation.py`
- `tests/blender_m11a_gui_validation.py`
- `tests/blender_m11a_validation.py`
- `tests/blender_m8_1_reload_validation.py`
- `tests/blender_m9_reload_validation.py`
- `tests/blender_m9_validation.py`
- `tests/blender_m9c_validation.py`
- `tests/m11a_mcp_transport_validation.py`
- `tests/test_assembly.py`
- `tests/test_m8.py`
- `tests/test_planes.py`
