#!/usr/bin/env python3
"""Run secret-safe NEYRONIX provider probes behind an explicit USD budget gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping

import httpx


class BudgetExceeded(RuntimeError):
    """Raised before a probe could exceed its authorized billing boundary."""


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    probe_id: str
    required_env: tuple[str, ...]
    estimated_cost_usd: float


@dataclass(slots=True)
class LiveProbeGate:
    allow_billable: bool
    max_usd: float
    reserved_usd: Decimal = Decimal("0")

    def reserve(self, spec: ProbeSpec) -> None:
        cost = Decimal(str(spec.estimated_cost_usd))
        if cost > 0 and not self.allow_billable:
            raise BudgetExceeded("billable live probes were not explicitly authorized")
        limit = Decimal(str(self.max_usd))
        if cost < 0 or self.reserved_usd + cost > limit:
            raise BudgetExceeded(
                f"probe {spec.probe_id} would exceed the authorized live-test budget"
            )
        self.reserved_usd += cost


PROBES: dict[str, ProbeSpec] = {
    "openai_auth": ProbeSpec("openai_auth", ("OPENAI_API_KEY",), 0.0),
    "comet_auth": ProbeSpec("comet_auth", ("COMET_API_KEY",), 0.0),
    "openai_text": ProbeSpec("openai_text", ("OPENAI_API_KEY",), 0.01),
    "tavily_search": ProbeSpec("tavily_search", ("TAVILY_API_KEY",), 0.01),
}

_SENSITIVE_KEY_PARTS = ("authorization", "api_key", "token", "secret", "password")


def redact_payload(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    """Return a recursively redacted copy suitable for logs and reports."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                result[str(key)] = "[redacted]"
            else:
                result[str(key)] = redact_payload(item, secrets=secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_payload(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[redacted]")
        return redacted
    return value


def _summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"response_type": type(payload).__name__}
    for key in ("data", "results", "output"):
        items = payload.get(key)
        if isinstance(items, list):
            return {"item_count": len(items)}
    return {"response_keys": sorted(str(key) for key in payload)[:12]}


async def _request_probe(
    spec: ProbeSpec,
    environ: Mapping[str, str],
) -> tuple[int, Any]:
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if spec.probe_id == "openai_auth":
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {environ['OPENAI_API_KEY']}"},
            )
        elif spec.probe_id == "comet_auth":
            base = str(environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
            response = await client.get(
                f"{base}/v1/models",
                headers={"Authorization": f"Bearer {environ['COMET_API_KEY']}"},
            )
        elif spec.probe_id == "openai_text":
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {environ['OPENAI_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": str(environ.get("OPENAI_MODEL") or "gpt-4.1-mini"),
                    "input": "Reply with exactly: OK",
                    "max_output_tokens": 8,
                },
            )
        elif spec.probe_id == "tavily_search":
            response = await client.post(
                "https://api.tavily.com/search",
                headers={
                    "Authorization": f"Bearer {environ['TAVILY_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": "OpenAI official website",
                    "search_depth": "basic",
                    "max_results": 1,
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
        else:
            raise ValueError(f"unsupported probe: {spec.probe_id}")
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"content_type": response.headers.get("content-type", "")}
        return response.status_code, payload


async def run_probe(
    spec: ProbeSpec,
    environ: Mapping[str, str],
    *,
    request: Callable[[ProbeSpec], Awaitable[tuple[int, Any]]] | None = None,
) -> dict[str, Any]:
    missing = [name for name in spec.required_env if not str(environ.get(name, "")).strip()]
    if missing:
        return {
            "id": spec.probe_id,
            "status": "skipped",
            "estimated_cost_usd": spec.estimated_cost_usd,
            "reason": "missing configuration",
            "missing": missing,
        }
    secrets = tuple(str(environ.get(name, "")) for name in spec.required_env)
    try:
        status, payload = (
            await request(spec)
            if request is not None
            else await _request_probe(spec, environ)
        )
    except Exception as exc:
        message = redact_payload(str(exc), secrets=secrets)
        return {
            "id": spec.probe_id,
            "status": "failed",
            "estimated_cost_usd": spec.estimated_cost_usd,
            "error_type": type(exc).__name__,
            "error": str(message)[:300],
        }
    result: dict[str, Any] = {
        "id": spec.probe_id,
        "status": "passed" if 200 <= status < 300 else "failed",
        "http_status": status,
        "estimated_cost_usd": spec.estimated_cost_usd,
        "summary": _summary(redact_payload(payload, secrets=secrets)),
    }
    return result


async def _run_selected(args: argparse.Namespace) -> dict[str, Any]:
    gate = LiveProbeGate(args.allow_billable, args.max_usd)
    results: list[dict[str, Any]] = []
    for probe_id in args.probe:
        spec = PROBES[probe_id]
        missing = [name for name in spec.required_env if not os.environ.get(name)]
        if not missing:
            gate.reserve(spec)
        results.append(await run_probe(spec, os.environ))
    return {
        "budget": {
            "authorized_usd": args.max_usd,
            "reserved_estimate_usd": float(gate.reserved_usd),
        },
        "results": results,
    }


def main() -> int:
    args = parse_args()
    try:
        payload = asyncio.run(_run_selected(args))
    except BudgetExceeded as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if all(row["status"] != "failed" for row in payload["results"]) else 1


def parse_args(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    environ = os.environ if environ is None else environ
    env_probe_ids = [
        item.strip()
        for item in str(environ.get("NEYRONIX_LIVE_PROBE_IDS", "")).split(",")
        if item.strip()
    ]
    env_allow_billable = str(
        environ.get("NEYRONIX_LIVE_PROBE_ALLOW_BILLABLE", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe",
        action="append",
        choices=sorted(PROBES),
        default=env_probe_ids,
        help="Probe to run; repeat for multiple providers.",
    )
    parser.add_argument(
        "--allow-billable",
        action="store_true",
        default=env_allow_billable,
    )
    parser.add_argument(
        "--max-usd",
        type=float,
        default=float(environ.get("NEYRONIX_LIVE_PROBE_MAX_USD", "0") or 0),
    )
    args = parser.parse_args(argv)
    if not args.probe:
        args.probe = ["openai_auth", "comet_auth"]
    return args


if __name__ == "__main__":
    raise SystemExit(main())
