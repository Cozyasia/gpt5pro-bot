from pathlib import Path
import base64
import zlib

root = Path(__file__).resolve().parents[1]
payload = root / "celebrity_selfie_v122_payload"
encoded = "".join((payload / name).read_text(encoding="ascii") for name in (
    "part_01.txt", "part_02.txt", "part_03.txt", "part_04.txt"
))
source = zlib.decompress(base64.b85decode(encoded)).decode("utf-8")
(root / "decoded_v122_runtime.py").write_text(source, encoding="utf-8")

main_lines = (root / "main.py").read_text(encoding="utf-8").splitlines()
needles = (
    "def _detect_faces_for_choice",
    "async def _image_bytes_from_response",
    "def _prepare_reference_image_for_gemini",
    "PIAPI_API_KEY",
)
out = []
for needle in needles:
    matches = [i for i, line in enumerate(main_lines) if needle in line]
    out.append(f"===== {needle} matches={matches} =====")
    for i in matches[:8]:
        start = max(0, i - 15)
        end = min(len(main_lines), i + 100)
        out.extend(f"{n + 1:06d}: {main_lines[n]}" for n in range(start, end))
        out.append("")
(root / "runtime_helper_excerpts.txt").write_text("\n".join(out), encoding="utf-8")
print(f"decoded {len(source)} chars; main lines={len(main_lines)}")
