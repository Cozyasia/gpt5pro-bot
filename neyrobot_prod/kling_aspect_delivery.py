"""Fit Kling image-to-video output to the selected canvas without cropping it."""
import json
import subprocess
import tempfile
from pathlib import Path

_SIZES = {'9:16': (720, 1280), '16:9': (1280, 720), '1:1': (720, 720)}

def normalize_kling_video(content: bytes, aspect: str) -> tuple[bytes, bool]:
    if aspect not in _SIZES or not content or len(content) > 300 * 1024 * 1024:
        raise ValueError('invalid video or target aspect')
    width, height = _SIZES[aspect]
    with tempfile.TemporaryDirectory(prefix='kling-aspect-') as tmp:
        src, dst = Path(tmp) / 'source.mp4', Path(tmp) / 'result.mp4'
        src.write_bytes(content)
        try:
            probe = subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=width,height,sample_aspect_ratio','-of','json',str(src)],
                capture_output=True, check=True, timeout=30)
            stream = json.loads(probe.stdout)['streams'][0]
            sw, sh = int(stream['width']), int(stream['height'])
            sar = stream.get('sample_aspect_ratio') or '1:1'
            a,b = map(int, sar.split(':')) if sar not in ('N/A','0:1') else (1,1)
            if sw <= 0 or sh <= 0 or a <= 0 or b <= 0:
                raise ValueError('invalid video dimensions')
            if sw * a * height == sh * b * width:
                return content, False
            # Keep the complete picture in the foreground; blurred duplicate fills the rest.
            graph=(f'[0:v]split=2[bg][fg];'
                   f'[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=20:1[bgv];'
                   f'[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fgv];'
                   f'[bgv][fgv]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]')
            subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-filter_complex_threads','1',
                '-i',str(src),'-filter_complex',graph,'-map','[v]','-map','0:a:0?',
                '-c:v','libx264','-preset','veryfast','-crf','21','-threads','2',
                '-c:a','aac','-b:a','128k','-movflags','+faststart',str(dst)],
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=240)
            output=dst.read_bytes()
            if len(output)<512 or len(output)>300*1024*1024:
                raise ValueError('invalid converted video size')
            return output, True
        except (subprocess.SubprocessError, OSError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError('cannot format video') from exc
