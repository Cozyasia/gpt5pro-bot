# -*- coding: utf-8 -*-
"""Reasoning, guideline retrieval and medical-card mapping for v111."""
from __future__ import annotations

import contextlib
import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from medical_v111_client import call_model, clean, fallbacks, flag, int_env, parse_json, plain, user_tier
from medical_v111_prompts import AUDIT_SYSTEM, AUTH_DOMAINS, REASON_SYSTEM


def _guideline_query(extraction: dict) -> str:
    parts = [extraction.get("document_type", ""), *(extraction.get("specialties") or []), *(extraction.get("body_regions") or [])]
    for finding in (extraction.get("findings") or [])[:6]:
        if isinstance(finding, dict):
            parts.extend([finding.get("organ_or_test", ""), finding.get("classification", ""), clean(finding.get("finding"), 120)])
    return ("current clinical guideline patient management " + " ".join(clean(item, 160) for item in parts if clean(item, 160)))[:800]


async def guideline_context(mod: Any, extraction: dict, tier: str) -> str:
    if not flag("MEDICAL_GUIDELINE_SEARCH", True):
        return ""
    if tier in {"free", "start"} and not flag("MEDICAL_GUIDELINE_SEARCH_BASIC", False):
        return ""
    key = str(getattr(mod, "TAVILY_API_KEY", "") or os.environ.get("TAVILY_API_KEY", "")).strip()
    if not key:
        return ""
    payload = {
        "api_key": key,
        "query": _guideline_query(extraction),
        "search_depth": "advanced",
        "max_results": 5,
        "include_domains": list(AUTH_DOMAINS),
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
        blocks = []
        for result in (response.json().get("results") or [])[:5]:
            if not isinstance(result, dict):
                continue
            url = clean(result.get("url"), 500)
            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if not any(domain == allowed or domain.endswith("." + allowed) for allowed in AUTH_DOMAINS):
                continue
            blocks.append(f"SOURCE: {clean(result.get('title'), 240)} | {url}\n{clean(result.get('content'), 1400)}")
        return "\n\n".join(blocks)[:6500]
    except Exception:
        return ""


def history_context(mod: Any, user: Any, extraction: dict) -> str:
    if user_tier(mod, user) not in {"pro", "ultimate"}:
        return ""
    try:
        import medical_card_v109_patch as card
    except Exception:
        return ""
    user_id = int(user.id)
    with contextlib.suppress(Exception):
        if not card._has_consent(mod, user_id):
            return ""
        profile_id = card._default_profile_id(mod, user_id)
        documents = card._list_docs(mod, user_id, profile_id, "", 20)
        terms = " ".join([*(extraction.get("specialties") or []), *(extraction.get("body_regions") or [])]).lower().split()
        rows = []
        for document in documents:
            row = card._doc_row(mod, user_id, document["id"])
            if not row:
                continue
            metadata = json.loads(card._dec(mod, row[12]) or "{}")
            searchable = (str(row[3]) + str(row[4]) + json.dumps(metadata, ensure_ascii=False)).lower()
            if terms and not any(term in searchable for term in terms if len(term) > 4):
                continue
            rows.append(f"{row[5] or document.get('date') or '?'} | {row[4]} | {clean(metadata.get('summary'), 700)}")
            if len(rows) >= 6:
                break
        return "PREVIOUS RECORDS FROM THIS PROFILE:\n" + "\n".join(rows) if rows else ""
    return ""


async def reason_and_audit(mod: Any, run: dict, extraction: dict, goal: str, user: Any, plan: dict) -> tuple[str, dict]:
    tier = user_tier(mod, user)
    guidelines = await guideline_context(mod, extraction, tier)
    history = history_context(mod, user, extraction)
    prompt = f"USER GOAL:\n{goal or 'Подробно объяснить документ, риски и действия.'}\n\nSTRUCTURED SOURCE:\n{json.dumps(extraction, ensure_ascii=False)}"
    if history:
        prompt += "\n\n" + history
    if guidelines:
        prompt += "\n\nAUTHORITATIVE GUIDELINE SNIPPETS:\n" + guidelines
    draft, reasoning_model = await call_model(
        mod, run, "reason", fallbacks(plan["reason"], "reason"), REASON_SYSTEM,
        prompt, plan["effort"], plan["max_output"], False,
    )
    audit_prompt = f"STRUCTURED SOURCE:\n{json.dumps(extraction, ensure_ascii=False)}\n\nDRAFT:\n{draft[:24000]}"
    if guidelines:
        audit_prompt += "\n\nGUIDELINE CONTEXT:\n" + guidelines
    audit_raw, audit_model = await call_model(
        mod, run, "audit", fallbacks(plan["audit"], "audit"), AUDIT_SYSTEM,
        audit_prompt, "medium", int_env("MEDICAL_AUDIT_MAX_OUTPUT", 5200, 1800, 8000), True,
    )
    audit = parse_json(audit_raw)
    corrected = plain(audit.get("corrected_answer"))
    answer = corrected if len(corrected) >= max(500, int(len(draft) * 0.45)) else plain(draft)
    metadata = {
        "reasoning_model": reasoning_model,
        "audit_model": audit_model,
        "guideline_search_used": bool(guidelines),
        "audit_pass": bool(audit.get("pass")),
        "audit_issues": audit.get("issues", []) if isinstance(audit.get("issues"), list) else [],
    }
    return answer, metadata


def card_metadata(extraction: dict, answer: str) -> dict:
    document_type = extraction.get("document_type", "")
    if "laboratory" in document_type:
        category = "labs"
    elif document_type == "prescription":
        category = "prescription"
    elif document_type in {"doctor_conclusion", "discharge_summary", "pathology_report", "cytology_report"}:
        category = "conclusion"
    elif document_type in {"ultrasound_report", "ct_report", "mri_report", "xray_report", "ecg_report", "raw_medical_image", "endoscopy_report"}:
        category = "imaging"
    else:
        category = "other"

    findings, measurements = [], []
    for finding in (extraction.get("findings") or [])[:60]:
        if not isinstance(finding, dict):
            continue
        label = " — ".join(part for part in [clean(finding.get("organ_or_test"), 180), clean(finding.get("finding"), 500)] if part)
        if label:
            detail = " | ".join(part for part in [clean(finding.get("classification"), 200), clean(finding.get("comparison"), 300), clean(finding.get("uncertainty"), 300)] if part)
            findings.append({"label": label, "detail": detail, "priority": "attention" if detail else "routine"})
        for measurement in finding.get("measurements", []) if isinstance(finding.get("measurements"), list) else []:
            measurements.append({
                "name": " — ".join(part for part in [clean(finding.get("organ_or_test"), 150), clean(measurement.get("name"), 150)] if part),
                "value_text": clean(measurement.get("value"), 100),
                "numeric_value": None,
                "unit": clean(measurement.get("unit"), 80),
                "reference": clean(measurement.get("reference"), 180),
            })

    medications = []
    for item in (extraction.get("medications_in_source") or [])[:50]:
        if not isinstance(item, dict) or not clean(item.get("name"), 200):
            continue
        medications.append({
            "name": clean(item.get("name"), 300),
            "dosage": clean(item.get("dose"), 200),
            "schedule": " — ".join(part for part in [clean(item.get("schedule"), 250), clean(item.get("duration"), 150)] if part),
            "start_date": "", "end_date": "", "source_kind": "document",
        })

    follow_up = [
        {"title": clean(item, 400), "suggested_period": "", "reason": "Рекомендация из исходного документа"}
        for item in (extraction.get("recommendations_in_source") or [])[:20]
    ]
    return {
        "title": extraction.get("document_title") or "Медицинский документ",
        "document_date": extraction.get("document_date") or "",
        "category": category,
        "specialty": ", ".join(extraction.get("specialties") or [])[:80],
        "organ_systems": extraction.get("body_regions") or [],
        "summary": clean(answer, 1200),
        "key_findings": findings,
        "measurements": measurements,
        "medications": medications,
        "follow_up": follow_up,
    }
