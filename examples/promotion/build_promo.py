"""Build the narrated explainer from real CAD renders and mechanism clips.

Install edge-tts, pillow and imageio-ffmpeg. Set PROMO_FONT to a Chinese-capable
font when building on a system without macOS Heiti. Temporary segments are
removed automatically; final media, captions and production metadata remain.
"""
import asyncio
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

import edge_tts
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

OUT=Path(__file__).resolve().parent
FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()
FONT=Path(os.environ.get('PROMO_FONT','/System/Library/Fonts/STHeiti Medium.ttc'))
FPS=24


def run(arguments):
    """Run FFmpeg and show its diagnostic only when encoding fails."""
    result=subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-y',*arguments],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr[-8000:])


def duration(path):
    """Read the media duration reported by FFmpeg's demuxer."""
    result=subprocess.run([FFMPEG,'-hide_banner','-i',str(path)],capture_output=True,text=True)
    match=re.search(r'Duration: (\d+):(\d+):([\d.]+)',result.stderr)
    assert match,result.stderr
    hours,minutes,seconds=map(float,match.groups())
    return hours*3600+minutes*60+seconds


def timestamp(seconds,ass=False):
    """Format a timestamp for SRT or ASS captions."""
    milliseconds=round(seconds*1000)
    hours,milliseconds=divmod(milliseconds,3600000)
    minutes,milliseconds=divmod(milliseconds,60000)
    whole,milliseconds=divmod(milliseconds,1000)
    return f'{hours}:{minutes:02}:{whole:02}.{milliseconds//10:02}' if ass else f'{hours:02}:{minutes:02}:{whole:02},{milliseconds:03}'


def overlay(chapter,index,path):
    """Draw editorial titles with a transparent window for the actual CAD media."""
    image=Image.new('RGBA',(1280,720),(16,25,40,255));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((462,72,1234,652),radius=14,fill=(37,51,68,255))
    draw.rounded_rectangle((464,74,1232,650),radius=12,fill=(0,0,0,0))
    white=(240,245,250);muted=(160,180,199);cyan=(87,213,226)
    def text(position,body,size,color=white):draw.text(position,body,font=ImageFont.truetype(str(FONT),size),fill=color,spacing=12)
    text((54,26),'BLENDER / PARAMETRIC CAD',23)
    text((972,28),'AI VOICE · 中文解说',19,muted)
    text((54,108),chapter['label'],17,cyan)
    text((52,159),chapter['title'],42)
    draw.rounded_rectangle((52,342,418,529),radius=14,fill=(26,40,58))
    for line,body in enumerate(chapter['details']):
        draw.ellipse((70,369+line*48,76,375+line*48),fill=cyan)
        text((91,358+line*48),body,23,muted)
    for dot in range(8):
        color=cyan if dot<=index else (46,65,83)
        draw.rounded_rectangle((54+dot*44,575,88+dot*44,580),radius=2,fill=color)
    text((54,599),f'{index+1:02} / 08',20,muted)
    draw.line((52,657,1230,657),fill=(39,56,74),width=1)
    if index==7:text((527,602),'github.com/wyp41/blender-parametric-cad',23,cyan)
    image.save(path)


async def synthesize(chapters,config,work):
    """Generate two speech segments at a time, including sentence timing metadata."""
    semaphore=asyncio.Semaphore(2)
    async def one(index,chapter):
        async with semaphore:
            speaker=edge_tts.Communicate(chapter['narration'],config['voice'],rate=config['rate'],boundary='SentenceBoundary')
            await speaker.save(str(work/f'{index}.mp3'),str(work/f'{index}.jsonl'))
            print('VOICE',index+1,flush=True)
    await asyncio.gather(*(one(i,c) for i,c in enumerate(chapters)))


def main():
    """Encode eight chapters, then concatenate them into one H.264/AAC MP4."""
    config=json.loads((OUT/'storyboard.json').read_text())
    all_cues=[];timeline=[];cursor=0.0
    font_name=ImageFont.truetype(str(FONT),24).getname()[0]
    with tempfile.TemporaryDirectory(prefix='blender-promo-') as temporary:
        work=Path(temporary)
        asyncio.run(synthesize(config['chapters'],config,work))
        for index,chapter in enumerate(config['chapters']):
            audio=work/f'{index}.mp3'
            length=math.ceil((duration(audio)+.75)*FPS)/FPS
            artwork=work/f'{index}.png';overlay(chapter,index,artwork)
            events=[json.loads(line) for line in (work/f'{index}.jsonl').read_text().splitlines()]
            header=f'''[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 0\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{font_name},26,&H00F5F7FB,&H00F5F7FB,&H00101928,&H00101928,0,0,0,0,100,100,0,0,1,1,0,2,50,50,17,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
            lines=[]
            for event_index,event in enumerate(events):
                start=.25+event['offset']/1e7;end=start+event['duration']/1e7
                if event_index+1<len(events):end=min(end,.25+events[event_index+1]['offset']/1e7-.001)
                body=event['text']
                lines.append(f'Dialogue: 0,{timestamp(start,True)},{timestamp(end,True)},Default,,0,0,0,,{body}\n')
                all_cues.append((cursor+start,cursor+end,body))
            subtitle=work/f'{index}.ass';subtitle.write_text(header+''.join(lines))
            sources=[(OUT/name).resolve() for name in chapter['media']]
            if len(sources)==1:
                visual=['-loop','1','-framerate',str(FPS),'-i',str(sources[0])] if sources[0].suffix=='.png' else ['-i',str(sources[0])]
            else:
                playlist=work/f'{index}-media.txt'
                entries=[]
                for source in sources:
                    entries.append(f"file '{source}'\n")
                    if source.suffix=='.png':entries.append(f'duration {length/len(sources)}\n')
                if sources[0].suffix=='.png':entries.append(f"file '{sources[-1]}'\n")
                playlist.write_text(''.join(entries))
                visual=['-f','concat','-safe','0','-i',str(playlist)]
            # Stretch each real motion sequence to the narration; partial-turn
            # output gears must not jump back to their starting phase in a loop.
            timing=f'setpts={length/sum(duration(p) for p in sources)}*(PTS-STARTPTS),tpad=stop_mode=clone:stop_duration=1,' if sources[0].suffix=='.mp4' else ''
            graph=f"[0:v]{timing}fps={FPS},scale=768:576:flags=lanczos,setsar=1[media];color=c=0x101928:s=1280x720:r={FPS}[bg];[bg][media]overlay=464:74:shortest=1[base];[base][1:v]overlay=0:0:shortest=1,subtitles='{subtitle}':fontsdir='{FONT.parent}',format=yuv420p[v];[2:a]adelay=250:all=1,apad,atrim=duration={length},asetpts=PTS-STARTPTS[a]"
            run([*visual,'-loop','1','-framerate',str(FPS),'-i',str(artwork),'-i',str(audio),
                 '-filter_complex',graph,'-map','[v]','-map','[a]','-t',str(length),
                 '-c:v','libx264','-preset','medium','-crf','25','-maxrate','700k','-bufsize','1400k',
                 '-r',str(FPS),'-c:a','aac','-b:a','96k','-ar','48000','-ac','2','-movflags','+faststart',str(work/f'{index}.mp4')])
            timeline.append({'chapter':index+1,'title':chapter['title'].replace('\n',' '),'start_seconds':cursor,'duration_seconds':length})
            cursor+=length
            print('ENCODED',index+1,length,'seconds',flush=True)
        playlist=work/'chapters.txt';playlist.write_text(''.join(f"file '{work/f'{i}.mp4'}'\n" for i in range(8)))
        output=OUT/'blender_cad_promo_zh.mp4'
        run(['-f','concat','-safe','0','-i',str(playlist),'-c','copy','-movflags','+faststart',str(output)])
        run(['-i',str(output),'-vn','-ac','1','-b:a','128k',str(OUT/'voiceover_zh.mp3')])
        run(['-ss','1.0','-i',str(output),'-frames:v','1','-q:v','2',str(OUT/'poster.jpg')])
    assert output.stat().st_size<10_000_000,'Keep the GitHub attachment below 10 MB.'
    (OUT/'captions_zh.srt').write_text('\n\n'.join(f'{i+1}\n{timestamp(start)} --> {timestamp(end)}\n{body}' for i,(start,end,body) in enumerate(all_cues))+'\n')
    (OUT/'production.json').write_text(json.dumps({'ai_generated_voice':True,'voice':config['voice'],
        'rate':config['rate'],'fps':FPS,'resolution':[1280,720],'duration_seconds':duration(output),
        'size_bytes':output.stat().st_size,'chapters':timeline,'captions':'speech sentence timestamps',
        'source':'actual CAD history rebuild renders and prescribed-motion mechanism clips'},ensure_ascii=False,indent=2))
    print('PROMO COMPLETE',round(cursor,2),'seconds',output.stat().st_size,'bytes',flush=True)


if __name__=='__main__':main()
