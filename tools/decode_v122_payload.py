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
print(f"decoded {len(source)} chars")
