"""Safe assembly of source video and an image-to-video continuation."""
from __future__ import annotations
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path


def _probe(path: Path) -> dict:
    exe = shutil.which('ffprobe')
    if not exe:
        raise RuntimeError('ffprobe недоступен: параметры видео не проверены')
    proc = subprocess.run([exe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                          capture_output=True, timeout=30, check=True)
    result = json.loads(proc.stdout)
    video = next((v for v in result.get('streams', []) if v.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('В MP4 не обнаружена видеодорожка')
    width, height = int(video.get('width') or 0), int(video.get('height') or 0)
    duration = float(result.get('format', {}).get('duration') or 0)
    if not (2 <= width <= 4096 and 2 <= height <= 4096 and math.isfinite(duration) and 0.1 <= duration <= 600):
        raise ValueError('Недопустимые размеры или длительность видео')
    return {'width':width, 'height':height, 'duration':duration,
            'audio': any(v.get('codec_type') == 'audio' for v in result.get('streams', []))}


def source_aspect(video: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix='continuation_probe_') as td:
        path=Path(td)/'source.mp4'; path.write_bytes(video)
        meta=_probe(path)
    ratio=meta['width']/meta['height']
    return min(('9:16','1:1','16:9'),key=lambda x: abs(math.log(ratio/({'9:16':9/16,'1:1':1,'16:9':16/9}[x]))))


def join_continuation(source: bytes, continuation: bytes) -> bytes:
    exe=shutil.which('ffmpeg')
    if not exe: raise RuntimeError('ffmpeg недоступен')
    with tempfile.TemporaryDirectory(prefix='continuation_join_') as td:
        a=Path(td)/'source.mp4'; b=Path(td)/'next.mp4'; out=Path(td)/'joined.mp4'
        a.write_bytes(source); b.write_bytes(continuation)
        first=_probe(a); second=_probe(b)
        width=first['width']-(first['width']%2); height=first['height']-(first['height']%2)
        filters=[]
        for i, meta in enumerate((first,second)):
            filters.append(f'[{i}:v:0]setpts=PTS-STARTPTS,fps=24,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]')
            if first['audio'] or second['audio']:
                duration=meta['duration']
                if meta['audio']:
                    filters.append(f'[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{i}]')
                else:
                    filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{i}]')
        filters.append('[v0][v1]concat=n=2:v=1:a=0[v]')
        has_audio=first['audio'] or second['audio']
        if has_audio: filters.append('[a0][a1]concat=n=2:v=0:a=1[a]')
        cmd=[exe,'-y','-hide_banner','-loglevel','error','-i',str(a),'-i',str(b),'-filter_complex_threads','1',
             '-filter_complex',';'.join(filters),'-map','[v]']
        if has_audio: cmd+=['-map','[a]','-c:a','aac','-b:a','128k']
        cmd+=['-c:v','libx264','-threads','1','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(out)]
        subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=600)
        meta=_probe(out)
        if abs(meta['duration']-(first['duration']+second['duration'])) > max(.3,.05*(first['duration']+second['duration'])):
            raise RuntimeError('Сборка обрезала видео')
        if first['audio'] and not meta['audio']:
            raise RuntimeError('Исходная аудиодорожка потеряна')
        return out.read_bytes()
