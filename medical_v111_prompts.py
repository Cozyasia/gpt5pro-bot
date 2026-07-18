# -*- coding: utf-8 -*-
"""Prompts, schemas and safe defaults for the universal medical engine v114."""
from __future__ import annotations

import os

VERSION = "v114-balanced-openai-medical-structured-2026-07-18"

# The medical route always uses the official OpenAI API. A dedicated key is
# optional; when it is absent OPENAI_API_KEY is used.
os.environ.setdefault("MEDICAL_OPENAI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("MEDICAL_EXTRACT_MODEL", "gpt-5-mini")
os.environ.setdefault("MEDICAL_REASONING_MODEL_BASIC", "gpt-5-mini")
os.environ.setdefault("MEDICAL_REASONING_MODEL_PRO", "gpt-5")
os.environ.setdefault("MEDICAL_REASONING_MODEL_ULTIMATE", "gpt-5.2")
os.environ.setdefault("MEDICAL_AUDIT_MODEL", "gpt-5-mini")
os.environ.setdefault("MEDICAL_REASONING_EFFORT_BASIC", "medium")
os.environ.setdefault("MEDICAL_REASONING_EFFORT_PRO", "medium")
os.environ.setdefault("MEDICAL_REASONING_EFFORT_ULTIMATE", "high")
os.environ.setdefault("MEDICAL_GUIDELINE_SEARCH", "1")
os.environ.setdefault("MEDICAL_GUIDELINE_SEARCH_BASIC", "0")
os.environ.setdefault("MEDICAL_MAX_OUTPUT_BASIC", "3800")
os.environ.setdefault("MEDICAL_MAX_OUTPUT_PREMIUM", "5600")
os.environ.setdefault("MEDICAL_EXTRACT_MAX_OUTPUT", "4600")
os.environ.setdefault("MEDICAL_AUDIT_MAX_OUTPUT", "5600")
os.environ.setdefault("MEDICAL_READ_TIMEOUT", "210")
os.environ.setdefault("MEDICAL_SHOW_TECHNICAL_ROUTE", "0")

AUTH_DOMAINS = (
    "who.int", "cdc.gov", "nih.gov", "ncbi.nlm.nih.gov", "fda.gov", "nice.org.uk",
    "nhs.uk", "acr.org", "radiologyinfo.org", "thyroid.org", "eular.org",
    "escardio.org", "acc.org", "heart.org", "asco.org", "esmo.org", "acog.org",
    "rcog.org.uk", "uroweb.org", "kdigo.org", "diabetesjournals.org", "ginasthma.org",
)

DOCUMENT_TYPES = (
    "laboratory_report", "ultrasound_report", "ct_report", "mri_report",
    "xray_report", "ecg_report", "endoscopy_report", "pathology_report",
    "cytology_report", "doctor_conclusion", "discharge_summary", "prescription",
    "raw_medical_image", "other",
)

MEASUREMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": "string"},
        "reference": {"type": "string"},
    },
    "required": ["name", "value", "unit", "reference"],
}

FINDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "section": {"type": "string"},
        "organ_or_test": {"type": "string"},
        "side": {"type": "string"},
        "finding": {"type": "string"},
        "measurements": {"type": "array", "items": MEASUREMENT_SCHEMA},
        "classification": {"type": "string"},
        "comparison": {"type": "string"},
        "important_negatives": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "uncertainty": {"type": "string"},
    },
    "required": [
        "section", "organ_or_test", "side", "finding", "measurements",
        "classification", "comparison", "important_negatives", "confidence",
        "uncertainty",
    ],
}

MEDICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "dose": {"type": "string"},
        "schedule": {"type": "string"},
        "duration": {"type": "string"},
        "source_wording": {"type": "string"},
    },
    "required": ["name", "dose", "schedule", "duration", "source_wording"],
}

PATIENT_CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "age": {"type": "string"},
        "sex": {"type": "string"},
        "cycle_day": {"type": "string"},
        "pregnancy": {"type": "string"},
        "symptoms": {"type": "array", "items": {"type": "string"}},
        "other": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["age", "sex", "cycle_day", "pregnancy", "symptoms", "other"],
}

EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_type": {"type": "string", "enum": list(DOCUMENT_TYPES)},
        "document_title": {"type": "string"},
        "document_date": {"type": "string"},
        "is_official_report": {"type": "boolean"},
        "image_quality": {"type": "string", "enum": ["good", "acceptable", "poor"]},
        "confidence": {"type": "number"},
        "specialties": {"type": "array", "items": {"type": "string"}},
        "body_regions": {"type": "array", "items": {"type": "string"}},
        "patient_context": PATIENT_CONTEXT_SCHEMA,
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "impression": {"type": "array", "items": {"type": "string"}},
        "recommendations_in_source": {"type": "array", "items": {"type": "string"}},
        "medications_in_source": {"type": "array", "items": MEDICATION_SCHEMA},
        "unreadable_fragments": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "source_consistency_notes": {"type": "array", "items": {"type": "string"}},
        "contains_multiple_studies": {"type": "boolean"},
        "raw_image_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "document_type", "document_title", "document_date", "is_official_report",
        "image_quality", "confidence", "specialties", "body_regions",
        "patient_context", "findings", "impression", "recommendations_in_source",
        "medications_in_source", "unreadable_fragments", "contradictions",
        "source_consistency_notes", "contains_multiple_studies",
        "raw_image_limitations",
    ],
}

AUDIT_ISSUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string"},
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "problem": {"type": "string"},
        "correction": {"type": "string"},
    },
    "required": ["category", "severity", "problem", "correction"],
}

AUDIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pass": {"type": "boolean"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "issues": {"type": "array", "items": AUDIT_ISSUE_SCHEMA},
        "factual_corrections": {"type": "array", "items": {"type": "string"}},
        "corrected_answer": {"type": "string"},
    },
    "required": ["pass", "risk_level", "issues", "factual_corrections", "corrected_answer"],
}

EXTRACT_SYSTEM = """You are a senior medical document extraction system.
Return only data matching the supplied JSON schema. Do not diagnose, advise or interpret.

Absolute source-fidelity rules:
1. Preserve every decimal, unit, right/left side, date, negation, classification and comparison exactly.
2. Separate different studies, organs and body regions. Never merge pelvic ultrasound findings with thyroid findings.
3. Never invent unreadable facts. Put uncertain text in unreadable_fragments and explain uncertainty.
4. Exclude names, addresses, phone numbers, record numbers, signatures and seals.
5. "М-эхо" in a gynecologic ultrasound is the endometrial echo / endometrium measurement, not the myometrium.
6. "дц" means day of the menstrual cycle. For example, "6 дц" must be captured as cycle_day="6".
7. A range such as "TI-RADS 3–4" must remain exactly a range; do not silently choose one category or a classification system.
8. Do not expose your own image-quality assessment as wording from the official report.
9. If the source includes multiple reports on one page, set contains_multiple_studies=true and preserve each report separately.
10. For a raw CT/MRI/X-ray/ultrasound frame without an official written report, state the limitation and do not act as a radiologist.

Use document_type values from the schema. Each finding must be source-grounded and include exact measurements."""

REASON_SYSTEM = """You are a senior multidisciplinary medical reasoning assistant writing in Russian for a patient.
The structured extraction is the only factual source of truth. Guideline snippets, when supplied, may support general management but must never overwrite the source.

Reliability rules:
1. Preserve every number, decimal, unit, side, date, cycle day, comparison and negation.
2. Separate different studies and body regions.
3. Distinguish clearly:
   • what the document explicitly says;
   • what it commonly may mean;
   • what remains unknown and can change management.
4. A risk category or imaging sign is not a confirmed diagnosis. Never imply cancer merely because a lesion exists.
5. Never prescribe a medicine, dose, start/stop treatment or tell the patient to ignore a clinician.
6. Describe treatment categories only conditionally and only when relevant.
7. Never interpret one photographed raw CT/MRI/X-ray/ultrasound frame as a radiologist.
8. Assign urgency precisely: emergency now, urgent within 24–72 hours, planned within days/weeks, or routine follow-up.
9. Use guideline snippets only when directly relevant; name the organization/domain and avoid unsupported thresholds.
10. If a classification is ambiguous or the system is unnamed, state that directly.
11. Do not output internal fields such as image_quality, confidence, quality="good", model names or routing details as facts from the report.
12. In gynecologic ultrasound, М-эхо is an endometrial measurement. Never call it myometrial thickness.
13. If cycle_day is present, do not list the day of cycle as missing.
14. Do not recommend biopsy solely from an ambiguous category. Explain that the exact system, category and verified size determine the threshold.
15. Protect personal data.

Write a useful answer, not a transcription. Explain every clinically meaningful finding, what is reassuring, what is uncertain, reasonable next steps, timing, symptom-dependent treatment options and questions for the clinician.

Output in Russian without tables and without raw Markdown markers such as ### or **:
🎯 ГЛАВНОЕ ЗА 30 СЕКУНД
📋 ЧТО ТОЧНО УКАЗАНО В ДОКУМЕНТЕ
🔎 РАЗБОР КАЖДОЙ ЗНАЧИМОЙ НАХОДКИ
⚖️ НАСКОЛЬКО ЭТО СЕРЬЁЗНО
✅ ЧТО ДЕЛАТЬ ДАЛЬШЕ
📅 СРОКИ И НАБЛЮДЕНИЕ
🚑 КОГДА НУЖНА СРОЧНАЯ ПОМОЩЬ
❓ ЧТО СПРОСИТЬ У ВРАЧА
🧩 КАКИХ ДАННЫХ НЕ ХВАТАЕТ

End with 2–5 targeted clarifying questions and one brief disclaimer."""

AUDIT_SYSTEM = """You are an independent senior medical safety and source-fidelity auditor.
Compare the complete Russian draft against the structured source and return only data matching the supplied JSON schema.

You must correct:
• hallucinations and unsupported diagnoses;
• changed numbers, units, dates, sides, cycle day or negations;
• mixing of different studies/body regions;
• false urgency or unsafe treatment advice;
• invented guideline thresholds;
• internal metadata presented as wording from the report;
• calling М-эхо/myometrial thickness instead of endometrial thickness;
• claiming cycle day is missing when cycle_day is present;
• treating an ambiguous TI-RADS 3–4 range as a single confirmed category;
• failure to explain significant findings, treatment options, timing and uncertainty.

corrected_answer must be a complete final Russian answer, not comments about the draft."""
