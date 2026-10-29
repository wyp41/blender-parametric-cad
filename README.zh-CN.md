# Blender Parametric CAD

[English · English video](README.md) | **简体中文**

面向 Blender **5.1.2** 的参数化 CAD 插件：可编辑 Part Studio、链接装配、持久引用、
MCP 自动化和按零件导出。

## 演示视频

**从草图到机械机构——中文 AI 配音与字幕**

约 1 分 44 秒，讲解真实 CAD 历史重建、链接装配、机构动画和毫米 STL 导出。
播放时打开声音即可听解说。[切换英文视频](README.md#showcase)。

https://github.com/user-attachments/assets/9b05c43b-fee1-4c39-bb27-5221fcf72fdf

[流程、字幕与制作脚本](examples/promotion/README.zh-CN.md) ·
[14 个机构、模型、STL 和公式](examples/mechanisms/README.zh-CN.md)

<details>
<summary>36 秒机构合集 · 无配音</summary>

https://github.com/user-attachments/assets/f0776b6b-0ca6-455e-9513-564a8cb349cb

</details>

## 从这里开始

下载 [0.18.1 安装包](https://github.com/wyp41/blender-parametric-cad/releases/tag/v0.18.1)。
在 Blender 中选择 **Edit → Preferences → Extensions → Install from Disk**，
选中 ZIP 并启用插件。在 3D 视图按 `N`，打开 **CAD**。

新建 Part Studio → 绘制闭合草图 → 拉伸或旋转 → 编辑/重建。
用 **Open Assembly Window** 将零件复用为链接实例。详细操作与 AI 连接配置统一见
[使用指南](docs/guide.zh-CN.md)。

## 支持的能力

- 单实体 Part Studio 历史、数值草图编辑及六种基本约束。
- 拉伸、旋转、刚体变换、镜像、等距离倒角和固定半径圆角。
- 支持范围内的持久平面/直边引用、回滚和保存重开。
- 扁平链接装配、独立实例位姿，以及共享源零件更新。
- 齿轮/齿条轮廓生成，以及原生驱动器指定的平面运动。
- 三维视口测量、按零件 STL/OBJ/PLY 导出、MCP 和直接 Python API。

UI/MCP 输入为**毫米/度**，直接 Python 几何 API 为**米/弧度**。
STL 导出为**毫米**，OBJ/PLY 保留米坐标。

## 文档导航

| 主题 | English | 简体中文 |
| --- | --- | --- |
| 安装、建模、装配、MCP、限制 | [User guide](docs/guide.md) | [使用指南](docs/guide.zh-CN.md) |
| 数据归属、引用、验证 | [Architecture and validation](docs/development.md) | [架构与验证](docs/development.zh-CN.md) |
| API 与代码示例 | [Complete API contract](skills/3d-modelling/references/blender_parametric_cad_api.md) | [API 使用参考](skills/3d-modelling/references/blender_parametric_cad_api.zh-CN.md) |
| 机构、公式、打印、数量清单 | [Mechanism gallery](examples/mechanisms/README.md) | [机构示例](examples/mechanisms/README.zh-CN.md) |
| 视频、讲稿、字幕、重建 | [Video production](examples/promotion/README.md) | [视频制作](examples/promotion/README.zh-CN.md) |

原 M6/M7/M8/M11A 阶段说明已合并到架构指南，原始报告仍保留在 Git 历史。
供 AI 客户端使用的[技能/API 入口](skills/3d-modelling/SKILL.md)维持稳定路径。

## 当前边界

目前是基于网格的教学/原型流程，不是通用精确 CAD 内核。尚未实现通用关节/接触动力学、
嵌套装配、多实体 Part、持久曲面/曲边、高级约束和 STEP 导出。
示例采用指定运动学，尚未经过实物打印和承载验证。支持范围和已执行检查见对应指南。
