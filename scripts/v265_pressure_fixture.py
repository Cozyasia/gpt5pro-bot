"""CI-only real resident pressure at strict entry; never imported by runtime.

A fixed ballast byte count cannot predict headroom after model/cache reclaim.
Allocate small resident chunks until measured headroom is half the production
reserve, then call the unchanged real guard. No memory readings are mocked.
"""
from neyrobot_prod import v265_strict_runtime_safety as safety


def arm_measured_pressure():
    original = safety._strict_preflight
    retained = []

    def pressured_preflight():
        target = safety._STRICT_HEADROOM_RESERVE // 2
        for _ in range(256):
            current, limit, rss, inactive = safety._reclaim_before_strict()
            _, headroom, _ = safety._effective_memory(current, limit, rss, inactive)
            if headroom is None:
                raise AssertionError('CI pressure fixture requires a finite cgroup limit')
            if headroom <= target:
                break
            size = min(4 * 1024 * 1024, headroom - target)
            chunk = bytearray(size)
            for offset in range(0, size, 4096):
                chunk[offset] = 1
            retained.append(chunk)
        else:
            raise AssertionError('could not establish bounded resident pressure')
        print('V265_MEASURED_PRESSURE added_bytes=%d effective_headroom=%d target=%d real_cgroup=true' %
              (sum(map(len, retained)), headroom, target), flush=True)
        # Must raise the production guard's own insufficient-headroom error.
        original()
        raise AssertionError('real production guard allowed unsafe measured headroom')

    safety._strict_preflight = pressured_preflight
