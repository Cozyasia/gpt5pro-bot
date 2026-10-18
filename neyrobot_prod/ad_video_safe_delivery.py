"""Safe Telegram video delivery and deterministic Russian ad overlays.

Timeouts are ambiguous: Telegram may have accepted a message. Never automatically
send another copy after a timeout without external reconciliation.
"""
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

class DeliveryUncertain(RuntimeError):
    pass

def delivery_state(path):
    p=Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"state":"new"}

def _save(path, data):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd, name=tempfile.mkstemp(dir=str(p.parent), prefix=".delivery-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f); f.flush(); os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name): os.unlink(name)

async def deliver_once(path, send):
    """send is an async callable returning a Telegram Message with message_id.
    A timed-out send is uncertain and must be reconciled manually, not retried.
    Store the journal on durable shared storage; coordinate workers with a lock.
    """
    state=delivery_state(path)
    if state["state"]=="sent": return state.get("message_id")
    if state["state"]!="new": raise DeliveryUncertain("Delivery pending/uncertain; no automatic resend")
    _save(path,{"state":"sending"})
    try:
        result=await send()
    except (TimeoutError, asyncio.TimeoutError) as exc:
        _save(path,{"state":"uncertain","reason":"timeout"})
        raise DeliveryUncertain("Telegram delivery may have succeeded") from exc
    except Exception:
        _save(path,{"state":"uncertain","reason":"send_error"})
        raise
    mid=getattr(result,"message_id",None)
    _save(path,{"state":"sent","message_id":mid})
    return mid

def render_russian_overlay(source, destination, captions, font_path, *, timeout=180, background=False):
    """Burn user-approved Russian captions onto an existing video, no AI charges.
    captions: [(start_seconds, end_seconds, text), ...].
    """
    if not Path(font_path).is_file(): raise FileNotFoundError(font_path)
    if not captions: raise ValueError("At least one caption required")
    filters=[]
    for start,end,text in captions:
        if not (0 <= start < end): raise ValueError("Invalid caption timing")
        # drawtext's expansion is disabled, avoiding % and backslash interpolation.
        escaped=(text.replace("\\","\\\\").replace(":","\\:").replace("'","\\'")
                    .replace(",","\\,").replace("[","\\[").replace("]","\\]"))
        font=str(font_path).replace("\\","\\\\").replace(":","\\:")
        filters.append(
            "drawtext=fontfile='"+font+"':text='"+escaped+
            "':expansion=none:fontcolor=white:fontsize=h/22:"
            ("box=1:boxcolor=black@0.55:boxborderw=18:" if background else "box=0:shadowcolor=black@0.85:shadowx=2:shadowy=3:")
            "x=(w-text_w)/2:y=h*0.73:"
            "enable='between(t,"+str(start)+","+str(end)+")'"
        )
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y",
         "-i",str(source),"-vf",",".join(filters),"-c:v","libx264",
         "-preset","veryfast","-crf","20","-c:a","copy","-movflags","+faststart",str(destination)]
    subprocess.run(cmd,check=True,timeout=timeout)
    return str(destination)
