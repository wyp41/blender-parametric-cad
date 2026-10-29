# 建模流程讲解视频

[首页](../../README.zh-CN.md) · [English video](README.md) | 简体中文

中文 AI 配音、中文步骤说明和烧录字幕，约 1 分 44 秒，1280×720、24 fps，H.264/AAC。
[下载中文版](blender_cad_promo_zh.mp4)。[切换英文视频](README.md)，英文版有独立配音和时间轴。

https://github.com/user-attachments/assets/9b05c43b-fee1-4c39-bb27-5221fcf72fdf

[中文封面](poster_zh.jpg)

## 视频章节

| 时间 | 内容 |
| --- | --- |
| 00:00 | 从草图 到机械机构 |
| 00:12 | 先定义参数 再生成草图 |
| 00:24 | 拉伸齿宽 切除轴孔 |
| 00:36 | 修改上游参数 重新计算模型 |
| 00:49 | 链接零件 组成传动机构 |
| 01:03 | 复用零件 探索更多机构 |
| 01:15 | 面向打印 保留验证记录 |
| 01:30 | 从第一对齿轮 开始你的设计 |

画面来自真实 CAD 草图/特征重建和机构运动渲染，不是鼠标操作录屏；左侧卡片是解说图文。
同一个 Part 的拉伸齿宽从 8 改成 12 mm，贯穿轴孔保留，`workflow/validation.json`
记录对应尺寸。

运动由公式驱动，并按解说时长放慢，不代表真实运行速度，也不是关节/接触动力学仿真。
实物打印与承载能力尚未验证。

## 配音、字幕与源码

两种配音都是 **AI 合成语音**，通过 [edge-tts](https://github.com/rany2/edge-tts) 使用
Microsoft Edge 在线神经语音服务：英文 `en-US-GuyNeural`、中文 `zh-CN-XiaoxiaoNeural`，
均为 `+3%` 语速。不使用真人声音克隆。字幕采用语音服务的句级时间戳，并限制相邻字幕
边界避免重叠。原中文视频、音轨及字幕保持不变。

| 资源 | English | 中文 |
| --- | --- | --- |
| 视频 | `blender_cad_promo_en.mp4` | `blender_cad_promo_zh.mp4` |
| 讲稿及图文 | `storyboard_en.json` | `storyboard_zh.json` |
| 可编辑字幕 | `captions_en.srt` | `captions_zh.srt` |
| 独立音轨 | `voiceover_en.mp3` | `voiceover_zh.mp3` |
| 生成/检查信息 | `production_en.json` | `production_zh.json` |
| 封面 | `poster_en.jpg` | `poster_zh.jpg` |

两种语言共用 `workflow/` 阶段渲染和已有机构片段。`render_workflow.py` 求值原始齿轮历史，
不覆盖基础模型。`build_promo.py` 合成图文、配音、字幕和视频，临时片段自动清理。

## 重新生成

在仓库根目录运行，替换实际 Blender 可执行文件：

```sh
blender --background --factory-startup --python-exit-code 1 --python examples/promotion/render_workflow.py
python3 -m venv /tmp/cad-promo-env
/tmp/cad-promo-env/bin/python -m pip install -r examples/promotion/requirements.txt
/tmp/cad-promo-env/bin/python examples/promotion/build_promo.py --language en
# 可选：仅重新生成中文资源。
/tmp/cad-promo-env/bin/python examples/promotion/build_promo.py --language zh
```

不指定 `--language` 时默认英文。配音需要网络访问微软语音服务。非 macOS Heiti 环境用
`PROMO_FONT=/path/to/a/suitable-font.ttf` 指定字体，中文需要支持 CJK 的字体。
FFmpeg 由 imageio-ffmpeg 提供。每次只覆盖所选语言的视频、音轨、字幕、封面和生成报告。
重新生成媒体后，需要重新上传 GitHub 附件，再更新公开 README 地址。

模型公式和制造限制见[机构说明](../mechanisms/README.zh-CN.md)，安装/MCP 配置见
[使用指南](../../docs/guide.zh-CN.md)。
