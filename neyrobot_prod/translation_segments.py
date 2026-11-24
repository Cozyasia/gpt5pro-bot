"""Plan bounded lip-sync segments on a shared video/audio timeline."""
import math


def plan_segments(duration: float) -> list[tuple[float, float]]:
    """Partition 2–180 seconds into contiguous segments of 2–10 seconds.

    Equal-sized segments prevent a short unusable tail while retaining the
    original total duration. The same boundaries must be used for audio/video.
    """
    duration = float(duration)
    if not math.isfinite(duration) or not 2 <= duration <= 180:
        raise ValueError("Video duration must be between 2 and 180 seconds")
    count = math.ceil(duration / 10)
    boundaries = [duration * index / count for index in range(count)] + [duration]
    return list(zip(boundaries, boundaries[1:]))


def _ffmpeg(*args: str, timeout: int = 180) -> None:
    import subprocess
    import shutil
    exe = shutil.which('ffmpeg')
    if not exe:
        raise RuntimeError('ffmpeg is unavailable')
    try:
        subprocess.run([exe, '-y', '-hide_banner', '-loglevel', 'error', *args],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('Video processing failed') from exc


def _split_one(source, directory, index, start, end):
    video = directory / f'input_{index:03}.mp4'
    audio = directory / f'audio_{index:03}.mp3'
    duration = end - start
    common = ['-ss', f'{start:.6f}', '-i', str(source), '-t', f'{duration:.6f}']
    _ffmpeg(*common, '-map', '0:v:0', '-an', '-c:v', 'libx264', '-threads', '1',
            '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video))
    _ffmpeg(*common, '-map', '0:a:0', '-vn', '-c:a', 'libmp3lame', '-b:a', '128k', str(audio))
    return video.read_bytes(), audio.read_bytes()


def _validate_video(path, expected_duration):
    import json
    import shutil
    import subprocess
    exe = shutil.which('ffprobe')
    if not exe:
        raise RuntimeError('ffprobe is unavailable')
    try:
        proc = subprocess.run([exe, '-v', 'error', '-select_streams', 'v:0',
                               '-show_entries', 'stream=codec_type,duration',
                               '-show_entries', 'format=duration', '-of', 'json', str(path)],
                              check=True, capture_output=True, timeout=30)
        data = json.loads(proc.stdout)
        if not data.get('streams'):
            raise ValueError('no video')
        actual = float(data['streams'][0].get('duration') or data['format']['duration'])
        if not math.isfinite(actual) or abs(actual-expected_duration) > max(.3, expected_duration * .04):
            raise RuntimeError('Lip-sync segment duration is incorrect')
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Invalid lip-sync video') from exc


def _media_duration(path):
    import json
    import shutil
    import subprocess
    exe = shutil.which('ffprobe')
    if not exe:
        raise RuntimeError('ffprobe is unavailable')
    try:
        proc = subprocess.run([exe, '-v', 'error', '-show_entries', 'format=duration',
                               '-of', 'json', str(path)], check=True, capture_output=True, timeout=30)
        duration = float(json.loads(proc.stdout)['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('invalid duration')
        return duration
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Cannot determine media duration') from exc


def _assemble(source, directory, outputs, duration):
    manifest = directory / 'list.txt'
    manifest.write_text(''.join(f"file 'part_{i:03}.mp4'\n" for i in range(len(outputs))), encoding='utf-8')
    output = directory / 'final.mp4'
    _ffmpeg('-f', 'concat', '-safe', '1', '-i', str(manifest), '-i', str(source),
            '-map', '0:v:0', '-map', '1:a:0', '-t', f'{duration:.6f}',
            '-c:v', 'libx264', '-threads', '1', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(output), timeout=600)
    if not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError('Lip-sync assembly failed')
    return output.read_bytes()


async def sync_translated_video(video: bytes, duration: float, sync_segment) -> bytes:
    """Synchronize contiguous segments; any provider error aborts the result.

    `video` must already contain the fitted translated audio. `sync_segment`
    receives video bytes, corresponding audio bytes and duration in ms.
    """
    import asyncio
    import tempfile
    from pathlib import Path
    spans = plan_segments(duration)
    if not video:
        raise ValueError('Video is empty')
    with tempfile.TemporaryDirectory(prefix='translation_lipsync_') as temp_dir:
        directory = Path(temp_dir)
        source = directory / 'source.mp4'
        source.write_bytes(video)
        outputs = []
        for index, (start, end) in enumerate(spans):
            segment, audio = await asyncio.to_thread(_split_one, source, directory, index, start, end)
            video_length, audio_length = await asyncio.gather(
                asyncio.to_thread(_media_duration, directory / f'input_{index:03}.mp4'),
                asyncio.to_thread(_media_duration, directory / f'audio_{index:03}.mp3'),
            )
            # Encoders may round the final frame down, making the actual clip
            # shorter than the requested segment despite MP3 encoder padding.
            available_ms = math.floor(min(end-start, video_length, audio_length, 10.0) * 1000)
            duration_ms = available_ms - 10 if available_ms >= 2010 else available_ms
            if duration_ms < 2000:
                raise RuntimeError(f'Lip-sync segment {index+1} is shorter than 2 seconds')
            result = await sync_segment(segment, audio, duration_ms)
            if not isinstance(result, (bytes, bytearray)) or len(result) < 1024:
                raise RuntimeError(f'Lip-sync segment {index+1} is invalid')
            path = directory / f'part_{index:03}.mp4'
            path.write_bytes(result)
            await asyncio.to_thread(_validate_video, path, end-start)
            outputs.append(path)
        result = await asyncio.to_thread(_assemble, source, directory, outputs, duration)
        await asyncio.to_thread(_validate_video, directory / 'final.mp4', duration)
        return result


async def kling_sync_segment(video: bytes, audio: bytes, duration_ms: int, publish, provider) -> bytes:
    """Submit one paired clip to the existing Kling integration once."""
    import asyncio
    if not video or not audio or not 2000 <= duration_ms <= 10000:
        raise ValueError('Invalid video, audio or duration for Kling')
    video_url = await asyncio.to_thread(publish, video, 'translation_video.mp4')
    audio_url = await asyncio.to_thread(publish, audio, 'translation_audio.mp3')
    if not all(str(url).startswith('https://') for url in (video_url, audio_url)):
        raise RuntimeError('Provider media URLs are unavailable')
    return await provider(video_url, audio_url, duration_ms=duration_ms)
