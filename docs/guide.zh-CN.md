# 使用指南

[首页](../README.zh-CN.md) · [English](guide.md) | 简体中文

## 安装与打开

使用已验证的 Blender **5.1.2**。从 [0.18.1 发布页](https://github.com/wyp41/blender-parametric-cad/releases/tag/v0.18.1)
下载插件 ZIP，在 **Edit → Preferences → Extensions** 的菜单中选择
**Install from Disk**，选中 ZIP 并启用 **Blender Parametric CAD**。
在 3D 视图按 `N` 打开侧栏，再选择 **CAD**。

## 手动建模

1. 在 **Model** 中点击 **+** 新建 Part Studio。
2. 在 `XY`、`XZ`、`YZ` 或支持的持久平面上创建草图。
3. 使用上下文 CAD 工具栏绘制闭合轮廓，支持直线、圆、圆弧、混合边界、多个区域及区域删除。
4. 添加数值尺寸或下表中的基本约束，然后结束草图编辑。
5. 选择 **Create Extrude** 或 **Create Revolve**。拉伸支持 `New`、`Add`、
   `Remove`、`Blind` 和 `Through All`；旋转体可以使用基准轴或 SketchLine 轴。
6. 选择历史条目进行编辑，点击 **Apply & Rebuild** 更新结果。支持范围内还可以使用
   Transform、Mirror、等距离 Chamfer 和固定半径 Fillet。
7. 保存 `.blend`，重开时会恢复 CAD 历史与引用。

**Model** 管理历史树、回滚/向前恢复、抑制及特征操作；**Sketch** 管理支撑面与草图编辑；
**Measure** 检查几何；**Output** 验证和导出。原生上下文工具栏图标提供绘图、选择及
特征参数；工具栏弹窗不可用时，Model 中也提供参数卡。绘图时第一次点击就是第一个点。

| 能力 | 支持范围 |
| --- | --- |
| 尺寸 | 长度、水平/竖直距离、距离、半径、直径 |
| 约束 | 水平、竖直、重合、平行、垂直、相等 |
| 矩形 | 四条可编辑 SketchLine，加上语义宽高元数据 |
| 草图支撑 | 基准平面，以及支持的语义/派生持久平面 |
| 边特征 | 持久直边；Shift 点击可多选 |
| 历史 | 编辑、删除、抑制、回滚、向前恢复、重建 |

特征无效时保留最后有效显示网格。失败特征为 `ERROR`，受影响的下游特征为 `BLOCKED`。
应修正上游历史，不要进入 Blender Edit Mode 修改自动生成的 `*_Result` 网格。

## 链接装配

选择 **Open Assembly Window**，创建 Assembly，通过 **Add Part** 复用 Part Studio。
实例共享源几何，同时拥有独立名称、位姿和抑制状态。**Transform** 使用毫米和 XYZ 角度；
**Edit Source Part** 打开已有源工作区。重建源零件后，所有链接实例更新，并保留位姿和运动。

被引用的 Part 不能直接删除，`PART_IN_USE` 会列出引用它的 Assembly/Instance。
先移除这些实例再删除。装配目前是扁平实例列表，没有 mates、通用关节、嵌套装配或接触
求解器。[机构示例](../examples/mechanisms/README.zh-CN.md) 使用原生 Blender 驱动器指定平面运动。

## 测量与导出

**Measure** 标尺选择两个视口点，显示真实三维距离、`ΔX/ΔY/ΔZ` 与毫米坐标。
它按照屏幕像素容差吸附附近的网格顶点，以及活动草图的端点/交点。按 `Esc` 退出，
或清除结果。测量不会新建 CAD 特征。

在 **Output** 中验证，然后按 Part Studio 分别导出：

| 输出/API | 长度 | 角度 |
| --- | --- | --- |
| UI 和语义 MCP 工具 | 毫米 | 度 |
| 直接 Python 几何 API | 米 | 弧度 |
| 0.18.1 起的 STL | 毫米，无需再次乘以 1000 | — |
| OBJ / PLY | 内核的米坐标 | — |

STL 导出不依赖 Scene 显示单位缩放。请在切片器核对预期尺寸；修改 Scene 单位标签
不能修复旧文件中已经错误缩放的坐标。

## 通过 MCP 连接 AI 客户端

插件提供自己的语义 CAD 服务，通用第三方 Blender MCP 插件不会自动提供这些工具。

如需绑定某个已打开的 Blender 窗口，在 CAD 面板展开 **CAD MCP Service**，点击
**Start Service in This Window**。配置下列客户端并启动/重启它，将绝对路径替换为实际仓库路径：

```json
{
  "mcpServers": {
    "blender-parametric-cad": {
      "command": "python3",
      "args": ["/absolute/path/to/blender_parametric_cad/mcp/server.py"],
      "env": {
        "BLENDER_CAD_PORT": "9800",
        "BLENDER_CAD_AUTOSTART": "1"
      }
    }
  }
}
```

客户端优先复用可访问的服务；没有服务时，自动启动一个可见 Blender worker。
设置 `BLENDER_CAD_AUTOSTART=0` 只允许连接已有窗口。端点锁防止重复启动；
已有进程无响应时会报告错误，不会另开窗口绕过它。

| 设置 | 用途 |
| --- | --- |
| `BLENDER_CAD_EXECUTABLE` | Blender 可执行文件；已经在 `PATH` 中时可省略 |
| `BLENDER_CAD_FILE` | 可选启动文件；复用活动服务时忽略 |
| `BLENDER_CAD_AUTOSAVE` | 可选的独立自动保存目标 |
| `BLENDER_CAD_ENDPOINT_FILE` | 共享端点 JSON，默认在系统临时目录 |
| `BLENDER_CAD_PORT` | 与 Blender 服务一致，默认 9800 |
| `BLENDER_CAD_HEADLESS=1` | 用于 CI/后台运行的 worker |
| `BLENDER_CAD_GPU_BACKEND` | 显式指定本机 Blender 构建支持的后端 |

macOS 后台启动器目前默认选择 OpenGL。本机已验证的 Blender 构建只接受 Metal，
因此后台检查使用 `BLENDER_CAD_GPU_BACKEND=metal`。应选择实际构建提供的后端。
从旧 worker 升级后重启 Blender，清理残留导入模块；Preferences 的顶层模块提示
与端口占用是不同问题。

使用工具返回的 UUID，不要依靠 Blender 对象名称或网格索引。典型流程是
`cad_create_part` → `cad_create_sketch` → `cad_sketch_add_rectangle` →
`cad_create_extrude` → `cad_get_history` → `cad_export_part`。
几何修改会求解/重建，失败时回滚。

需要执行受信任的任意 Python 时，`blender_execute_python` 在 Blender 主线程运行，
保留命名空间，返回 stdout、stderr 和末尾表达式。它具有完整 Python/`bpy` 权限。
需要 CAD 历史、单位和验证时，优先使用语义 `cad_*` 工具。参数与示例见
[中文 API 使用参考](../skills/3d-modelling/references/blender_parametric_cad_api.zh-CN.md)及
[完整英文 API 契约](../skills/3d-modelling/references/blender_parametric_cad_api.md)。

## 限制与下一步

支持的平面/直边引用能随支持的编辑和重开操作恢复；引用缺失或有歧义时阻止下游计算，
不会猜测匹配。尚未实现曲面草图支撑、曲边/切向链引用、可变半径圆角、非对称倒角、
多实体 Part、通用拓扑命名或 STEP 导出。Tangent、Symmetric、Midpoint、Concentric、
Fix 等高级草图约束和通用自由度分析也不在当前范围内。

实践请看[机构示例](../examples/mechanisms/README.zh-CN.md)，数据归属、引用匹配与验证证据
请看[架构与验证](development.zh-CN.md)。实际打印和载荷仍需实测，机构文档列出了具体检查范围。
