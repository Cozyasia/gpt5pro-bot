"""Validate authorised, offline vendor exports for the frozen seven-case matrix."""

import argparse
import json
from pathlib import Path

from neyrobot_prod.v265_vendor_identity import FROZEN_CASES, load_export, qualification_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifacts = {}
    for case in FROZEN_CASES:
        path = args.exports / f"{case}.json"
        if path.exists():
            artifacts[case] = load_export(path, expected_case=case)
    report = qualification_status(artifacts)
    report["protocol"] = "v265-frozen-seven-case-vendor-identity-v1"
    report["network_calls"] = 0
    report["secrets_loaded"] = 0
    report["vendors"] = sorted({x.vendor for x in artifacts.values()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["ready_for_geometry_benchmark"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

