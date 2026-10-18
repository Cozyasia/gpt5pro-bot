"""Variable-length Seedance Studio FFmpeg assembly (not Veo's fixed scene assembler)."""
import json
import subprocess
from pathlib import Path

def _probe(path):
    p = subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],
                       capture_output=True,text=True,check=True,timeout=30)
    return json.loads(p.stdout)

def assemble_seedance_video(clips, destination, duration_seconds, *, width=720, height=1280):
    """Join variable-length clips; reject insufficient footage rather than silently padding."""
    target = float(duration_seconds)
    if not 4 <= target <= 30 or not clips:
        raise ValueError("Invalid Seedance Studio duration or empty clips")
    if width < 256 or height < 256 or width % 2 or height % 2:
        raise ValueError("Invalid dimensions")
    paths = [Path(p).resolve() for p in clips]
    output = Path(destination).resolve()
    if output in paths or not all(p.is_file() for p in paths):
        raise ValueError("Invalid input or output paths")
    info = [_probe(p) for p in paths]
    lengths = [float(m["format"]["duration"]) for m in info]
    if sum(lengths) + 0.15 < target:
        raise ValueError(f"Insufficient Seedance footage: {sum(lengths):.2f}s for {target:.2f}s")
    if any(not any(s.get("codec_type") == "video" for s in m["streams"]) for m in info):
        raise ValueError("Missing video stream")
    output.parent.mkdir(parents=True, exist_ok=True)
    filters = []
    for i, m in enumerate(info):
        filters.append(f"[{i}:v:0]fps=24,scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[v{i}]")
        if any(s.get("codec_type") == "audio" for s in m["streams"]):
            filters.append(f"[{i}:a:0]aresample=48000,asetpts=PTS-STARTPTS[a{i}]")
        else:
            filters.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                           f"atrim=duration={lengths[i]:.6f},asetpts=PTS-STARTPTS[a{i}]")
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
    filters.append(f"{streams}concat=n={len(paths)}:v=1:a=1[v][a]")
    cmd = ["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y"]
    for path in paths:
        cmd += ["-i",str(path)]
    cmd += ["-filter_complex",";".join(filters),"-map","[v]","-map","[a]",
            "-t",str(target),"-c:v","libx264","-preset","veryfast",
            "-pix_fmt","yuv420p","-c:a","aac","-b:a","128k",
            "-movflags","+faststart",str(output)]
    result = subprocess.run(cmd,capture_output=True,timeout=600)
    if result.returncode:
        raise RuntimeError("Seedance FFmpeg assembly failed: "+result.stderr[-2000:].decode("utf-8","replace"))
    actual = float(_probe(output)["format"]["duration"])
    if abs(actual-target) > 0.15:
        raise RuntimeError(f"Seedance output duration mismatch: {actual:.2f}s vs {target:.2f}s")
    return output
