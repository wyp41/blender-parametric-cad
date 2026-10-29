# Blender Parametric CAD

**English** | [简体中文 · 中文视频](README.zh-CN.md)

A parametric CAD extension for Blender **5.1.2**: editable Part Studios, linked
Assemblies, persistent references, MCP automation, and per-Part export.

## Showcase

**From sketches to mechanisms — English AI narration and captions**

A two-minute walkthrough of actual CAD history rebuilds, linked Assemblies,
mechanism animation, and millimeter STL export. Turn on sound for narration.
[Watch in Chinese / 观看中文版](README.zh-CN.md).

https://github.com/user-attachments/assets/34792266-2585-4eb0-b195-aaa571f0a271

[Workflow, captions and production scripts](examples/promotion/README.md) ·
[14 mechanisms, models, STL files and formulas](examples/mechanisms/README.md)

<details>
<summary>36-second mechanism montage · no narration</summary>

https://github.com/user-attachments/assets/f0776b6b-0ca6-455e-9513-564a8cb349cb

</details>

## Start here

Download the [0.18.1 release](https://github.com/wyp41/blender-parametric-cad/releases/tag/v0.18.1).
In Blender, choose **Edit → Preferences → Extensions → Install from Disk**,
select the ZIP and enable the extension. Press `N` in the 3D View and open **CAD**.

Create a Part Studio → draw a closed Sketch → Extrude or Revolve → edit/rebuild.
Use **Open Assembly Window** to reuse Parts as linked instances. For step-by-step
instructions and AI connection settings, see the [user guide](docs/guide.md).

## What it supports

- Single-body Part Studio history, numeric Sketch editing and six basic constraints.
- Extrude, Revolve, Transform, Mirror, equal-distance Chamfer and constant-radius Fillet.
- Persistent supported planar/straight-edge references, rollback and save/reopen.
- Flat linked Assemblies with independent placements and shared source updates.
- Gear/rack profile helpers and native prescribed planar-motion drivers.
- 3D viewport measurement, per-Part STL/OBJ/PLY export, MCP and direct Python APIs.

UI/MCP inputs use **mm/degrees**; direct Python geometry uses **meters/radians**.
STL is exported in **mm**; OBJ/PLY retain meter coordinates.

## Documentation

| Topic | English | 简体中文 |
| --- | --- | --- |
| Install, modeling, Assemblies, MCP, limits | [User guide](docs/guide.md) | [使用指南](docs/guide.zh-CN.md) |
| Data ownership, references, tests | [Architecture and validation](docs/development.md) | [架构与验证](docs/development.zh-CN.md) |
| APIs and code examples | [Complete API contract](skills/3d-modelling/references/blender_parametric_cad_api.md) | [API 使用参考](skills/3d-modelling/references/blender_parametric_cad_api.zh-CN.md) |
| Mechanisms, formulas, printing, BOM | [Mechanism gallery](examples/mechanisms/README.md) | [机构示例](examples/mechanisms/README.zh-CN.md) |
| Videos, narration, captions, rebuild | [Video production](examples/promotion/README.md) | [视频制作](examples/promotion/README.zh-CN.md) |

The former M6/M7/M8/M11A notes are consolidated in the architecture guide;
original reports remain in Git history. AI clients retain the stable
[skill/API entry point](skills/3d-modelling/SKILL.md).

## Current boundaries

This is a mesh-based teaching/prototype workflow, not a general exact CAD kernel.
General joints/contact dynamics, nested Assemblies, multi-body Parts, curved
persistent supports/edges, advanced constraints and STEP export are absent.
The examples use prescribed kinematics and have not been physically print-tested
or load-rated. See the guides for supported inputs and recorded validation.
