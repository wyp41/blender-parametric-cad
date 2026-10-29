# Mechanism gallery

[Home](../../README.md) · English | [简体中文](README.zh-CN.md)

Fourteen motion examples extend the original module-2, 20/40-tooth gear document,
reusing 25 independent Parts. Both original gear UUIDs are preserved.
`base_spur_gears.blend` is the starting document; `mechanism_course_gallery.blend`
is the final project. Validated with Blender 5.1.2 / Parametric CAD 0.18.1.

[Watch the English narrated modeling workflow](../promotion/README.md), or
[switch to the Chinese explanation](../promotion/README.zh-CN.md).

![Mechanism overview](overview.png)

https://github.com/user-attachments/assets/f0776b6b-0ca6-455e-9513-564a8cb349cb

[Download the 35.6-second montage](mechanism_showcase.mp4). `videos/` contains
individual MP4s and `previews/` contains stills. Every fourth frame of the
240-frame motion is sampled and played at 24 fps, roughly 4× the Blender
timeline speed. Individual clips do not necessarily form seamless loops.

## Mechanisms and course relations

Gears use module 2 mm, pressure angle 20°, face width 8 mm and external-gear bores
of 6.3 mm. Each gear's nominal tangential tooth-thickness reduction is 0.15 mm,
giving 0.30 mm total nominal backlash for an external pair. Actual printed
clearance depends on material, printer and orientation.

| Scene | Mechanism | Parameters and relationship |
| --- | --- | --- |
| 01 | External spur pair | 20→40; output speed −1/2; center distance 60 mm |
| 02 | Idler train | 20→20→40; output speed +1/2 |
| 03 | Compound reduction | 20/40 × 20/40; output speed +1/4 |
| 04 | Reverted train | Coaxial input/output, two 60 mm center distances; 4:1 reduction |
| 05 | Rack and pinion | z20, pitch radius 20 mm; x=rθ; 125.664 mm travel/turn; bounded reciprocating animation |
| 06 | Internal gear pair | z20/z80, 60 mm centers; same direction, output speed +1/4 |
| 07 | Planetary, ring fixed | Sun40 + three Planet20 + Ring80; sun input, carrier output; 3:1 reduction |
| 08 | Planetary, sun fixed | Ring input, carrier output; speed ratio +2/3 |
| 09 | Planetary, carrier fixed | Sun input, ring output; speed ratio −1/2 |
| 10 | Planetary differential | Sun speed 1, ring 1/2, carrier 2/3 |
| 11 | Inline slider-crank | Crank20, rod60 mm; x=r cosθ+√(l²−r²sin²θ); 40 mm stroke |
| 12 | Crank-rocker four-bar | Ground60, crank20, coupler60, rocker40 mm; upper circle-intersection branch |
| 13 | Eccentric circular cam / flat follower | R30, eccentricity10 mm; y=30+10 sinθ; 20 mm stroke, gravity return |
| 14 | Scotch yoke | Crank20 mm, slot width6.4 mm; x=20 cosθ; 40 mm stroke |

The planetary geometry satisfies zR=zS+2zP, and uniform assembly is possible
because (zS+zR)/3=40 is an integer. Willis' relation is
`(ωS−ωC)/(ωR−ωC)=−zR/zS`, equivalently `ωC=(ωS+2ωR)/3`.
Absolute planet spin is `ωP=3ωC−2ωS`. All speeds share the same positive direction.

The formulas are independently implemented from these course/manufacturer sources:

- [MIT FUNdaMENTALS, Topic 6: Power Transmission Elements](https://meddevdesign.mit.edu/wp-content/uploads/simple-file-list/FUNdaMentals-Chapters/FUNdaMENTALs-Topic-6.pdf): gear trains and transmission design.
- [KHK Internal Gears catalog](https://khkgears.net/pdf/2023/internal-gears.pdf): internal-gear interference and the three-planet 40/20/80 combination.
- [CMU Introduction to Mechanisms, Chapter 5](https://www.cs.cmu.edu/~rapidproto/mechanisms/chpt5.html): linkages and slider mechanisms.
- [CMU Chapter 6: Cams](https://www.cs.cmu.edu/~rapidproto/mechanisms/chpt6.html): cams, followers and return constraints.
- [METU: Slider Crank](https://ocw.metu.edu.tr/pluginfile.php/3961/mod_resource/content/11/ch7/7-2.htm): inline slider-crank stroke relations.
- [Prusa: Modeling with 3D printing in mind](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135): orientation, clearances and trial prints.

## Open and reproduce

Open `mechanism_course_gallery.blend`, choose scene 01–14 and press Space.
Native Blender drivers persist in the file. With 0.18.1 installed, edit source
Sketches/features, rebuild the Part and synchronize its linked instances.
For installation/MCP setup use the [user guide](../../docs/guide.md).

From the repository root, replace `blender` with your executable:

```sh
blender --background --factory-startup --python-exit-code 1 --python examples/mechanisms/generate.py
blender --background --factory-startup --python-exit-code 1 --python examples/mechanisms/render_gallery.py
```

The first command rebuilds from the base document and overwrites models,
validation, STL and previews here. The second renders videos. Generator inputs
construct ordinary Sketch/Extrude/Revolve features; regenerate from the base to
change tooth counts and similar inputs. There is no dedicated Gear Feature type.
`catalog.json` maps Part/Assembly/instance IDs; [BOM.csv](BOM.csv) records each
scene's print quantities and support requirements.

## Printing and assembly

`stl/` contains one export per independent Part in **millimeters**; do not scale
by 1000 in the slicer. Lay Parts on their local XY bed faces. Print the compound
gear large gear down, so its full face supports the upper pinion; print shouldered
pins head down. The ring OD is 181 mm and the longest base is 180 mm, fitting a
common 220×220 mm bed.

PLA FDM with a 0.4 mm nozzle / 0.2 mm layers is a trial starting point. The pins
are 5.8 mm and bores 6.3 mm; guides also include clearance. Trial-print the fit
rather than assuming these tolerances work on every printer. The 0.6 mm spacers
are three layers: ensure the slicer retains them. Remove elephant's foot/burrs
and check low-speed manual motion after assembly.

Scenes 02–05 and 11–14 include printed fixtures, guides/pins and axial spacers.
They still need suitable removable axial retainers. Scenes 01 and 06–10 focus
on transmission relationships and **do not include complete bearing housings,
ring supports or axial retention**. Supply an external frame/shafts and support
the carrier's underside clearance. These are printable mechanism components,
not complete ready-to-run gearboxes.

The cam uses gravity return: mount its motion plane vertically so gravity holds
the follower against the cam. There is no return spring. Integral printed pins
and bases are intended for manual, low-load teaching trials, not high-speed or
load-bearing use.

## What was checked

`validation.json` records manifold positive-volume meshes, STL bounds and motion
samples. Each scene has 73 samples across frames 1–241. BVH triangle checks
cover gear pairs and fixtures; planet world positions/spin and linkage closure
are checked. Save/reopen compares all instance transforms at frames 1.25, 31 and
121. Intended spacer bearing-face contact and cam/follower contact are excluded
from penetration checks. Small Z offsets avoid coplanar false positives, so
these checks do not measure axial face clearance.

Discrete sampling is not proof of interference-free continuous motion. No
physical print, strength, fatigue, friction, contact force, lubrication or motor
selection tests have been performed. Motion is analytically prescribed;
there is no general joint/contact dynamics solver. Gear flanks are sampled
involutes with circular roots, not an exact hob-generated trochoid. Unsupported
undercut/profile input ranges are rejected.

`plugin_regression.json` records mm export bounds, material preservation, tiny
translation/rotation, Assembly sync, source rebuild, reload and the static-motion
no-op. Forty-one focused Python checks and the existing M11A integration check
also passed. Broader architectural evidence is consolidated in
[Architecture and validation](../../docs/development.md).

Issues exposed by the gallery and fixed in 0.18.1 include dense-profile
recursion/performance, STL meter→millimeter conversion, lost rebuild materials,
Assembly sync baking animated transforms, F-curves swallowing small positive
translations, and a static-instance helper error. This covers a useful set of
teaching workflows; general engineering constraints, joint solving and physical
manufacturing validation remain further work.
