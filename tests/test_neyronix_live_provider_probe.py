import asyncio

import pytest

from ops.neyronix_live_provider_probe import (
    BudgetExceeded,
    LiveProbeGate,
    ProbeSpec,
    parse_args,
    redact_payload,
    run_probe,
)


def test_live_probe_gate_requires_explicit_billable_authorization():
    gate = LiveProbeGate(allow_billable=False, max_usd=10.0)

    with pytest.raises(BudgetExceeded, match="explicitly authorized"):
        gate.reserve(ProbeSpec("openai_text", ("OPENAI_API_KEY",), 0.01))


def test_live_probe_gate_refuses_to_exceed_total_budget():
    gate = LiveProbeGate(allow_billable=True, max_usd=0.50)
    gate.reserve(ProbeSpec("first", ("KEY",), 0.30))

    with pytest.raises(BudgetExceeded, match="budget"):
        gate.reserve(ProbeSpec("second", ("KEY",), 0.21))


def test_redact_payload_removes_nested_secrets_and_token_fields():
    payload = {
        "ok": True,
        "authorization": "Bearer top-secret",
        "nested": {"api_key": "top-secret", "message": "failed top-secret"},
    }

    redacted = redact_payload(payload, secrets=("top-secret",))

    assert redacted == {
        "ok": True,
        "authorization": "[redacted]",
        "nested": {"api_key": "[redacted]", "message": "failed [redacted]"},
    }


def test_run_probe_reports_sanitized_success_without_returning_response_body():
    spec = ProbeSpec("comet_auth", ("COMET_API_KEY",), 0.0)

    async def request(_spec):
        return 200, {"data": [{"id": "model-a"}], "token": "provider-secret"}

    result = asyncio.run(
        run_probe(spec, {"COMET_API_KEY": "provider-secret"}, request=request)
    )

    assert result == {
        "id": "comet_auth",
        "status": "passed",
        "http_status": 200,
        "estimated_cost_usd": 0.0,
        "summary": {"item_count": 1},
    }


def test_run_probe_skips_when_required_configuration_is_missing():
    spec = ProbeSpec("tavily_search", ("TAVILY_API_KEY",), 0.01)

    async def request(_spec):
        raise AssertionError("request must not run")

    result = asyncio.run(run_probe(spec, {}, request=request))

    assert result["status"] == "skipped"
    assert result["reason"] == "missing configuration"
    assert result["missing"] == ["TAVILY_API_KEY"]


def test_parse_args_uses_explicit_startup_probe_environment():
    args = parse_args([], {
        "NEYRONIX_LIVE_PROBE_IDS": "openai_auth,comet_auth,openai_text,tavily_search",
        "NEYRONIX_LIVE_PROBE_ALLOW_BILLABLE": "1",
        "NEYRONIX_LIVE_PROBE_MAX_USD": "0.02",
    })

    assert args.probe == [
        "openai_auth", "comet_auth", "openai_text", "tavily_search",
    ]
    assert args.allow_billable is True
    assert args.max_usd == 0.02
