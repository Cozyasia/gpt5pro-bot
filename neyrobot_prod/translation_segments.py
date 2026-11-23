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
