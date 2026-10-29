# Narrated modeling workflow

[Home](../../README.md) · English | [中文视频 / 简体中文](README.zh-CN.md)

English AI narration, English chapter cards and burned-in captions. About 2:02,
1280×720 at 24 fps, H.264/AAC. [Download the English video](blender_cad_promo_en.mp4).
For Chinese narration and its own timing, [switch languages](README.zh-CN.md).

https://github.com/user-attachments/assets/34792266-2585-4eb0-b195-aaa571f0a271

[English poster](poster_en.jpg)

## Chapters

| Time | Topic |
| --- | --- |
| 00:00 | From sketches to mechanisms |
| 00:14 | Start with parameters |
| 00:29 | Extrude. Cut the bore. |
| 00:42 | Edit upstream. Rebuild. |
| 00:56 | Link parts. Drive motion. |
| 01:12 | Reuse parts. Explore motion. |
| 01:28 | Export parts. Keep evidence. |
| 01:44 | Build your first gear pair. |

The media uses actual CAD Sketch/feature rebuilds and rendered mechanism motion;
it is not a mouse-operation screen recording. The left cards are explanatory
editorial graphics. One Part's Extrude width changes from 8 to 12 mm while the
Through All bore remains. `workflow/validation.json` records the stage bounds.

Motion is formula-driven and time-stretched for the explanation, not a real
operating-speed or joint/contact dynamics simulation. Physical printing and
load capacity remain untested.

## Voice, captions and sources

Both voices are **AI-generated** using [edge-tts](https://github.com/rany2/edge-tts)
and Microsoft Edge's online neural speech service: English `en-US-GuyNeural`,
Chinese `zh-CN-XiaoxiaoNeural`, both at `+3%`. No real-person voice cloning is used.
Sentence timestamps from the service drive the captions; adjacent cues are
clamped to prevent overlap. The original Chinese video/audio/captions are retained.

| Asset | English | Chinese |
| --- | --- | --- |
| Video | `blender_cad_promo_en.mp4` | `blender_cad_promo_zh.mp4` |
| Narration and graphics | `storyboard_en.json` | `storyboard_zh.json` |
| Editable captions | `captions_en.srt` | `captions_zh.srt` |
| Separate voice track | `voiceover_en.mp3` | `voiceover_zh.mp3` |
| Production/check metadata | `production_en.json` | `production_zh.json` |
| Poster | `poster_en.jpg` | `poster_zh.jpg` |

Both languages share `workflow/` stage renders and the existing mechanism clips.
`render_workflow.py` evaluates the original gear history without overwriting the
base model. `build_promo.py` composes titles, speech, captions and video, and
cleans temporary segments automatically.

## Rebuild

From the repository root, substitute your Blender executable:

```sh
blender --background --factory-startup --python-exit-code 1 --python examples/promotion/render_workflow.py
python3 -m venv /tmp/cad-promo-env
/tmp/cad-promo-env/bin/python -m pip install -r examples/promotion/requirements.txt
/tmp/cad-promo-env/bin/python examples/promotion/build_promo.py --language en
# Optional: regenerate only Chinese outputs.
/tmp/cad-promo-env/bin/python examples/promotion/build_promo.py --language zh
```

English is the default if `--language` is omitted. Speech generation needs network
access to Microsoft's service. On systems without macOS Heiti, set
`PROMO_FONT=/path/to/a/suitable-font.ttf`; Chinese needs a CJK-capable font.
imageio-ffmpeg supplies FFmpeg. Each build overwrites only the selected language's
video, audio, captions, poster and production report. Rebuilt media needs a new
GitHub attachment upload before updating the public README URL.

For the model formulas and manufacturing limits, use the
[mechanism guide](../mechanisms/README.md); for installation/MCP use the
[user guide](../../docs/guide.md).
