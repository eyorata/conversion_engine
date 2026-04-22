"""Day 0 smoke test. Runs each integration independently and prints a pass/fail matrix.

Usage:
  python -m scripts.day0_smoke_test all
  python -m scripts.day0_smoke_test sms
  python -m scripts.day0_smoke_test hubspot
  python -m scripts.day0_smoke_test calcom
  python -m scripts.day0_smoke_test langfuse
  python -m scripts.day0_smoke_test openrouter
  python -m scripts.day0_smoke_test cfpb
  python -m scripts.day0_smoke_test crunchbase
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from agent.config import get_settings
from agent.logging_setup import setup_logging

setup_logging()
settings = get_settings()


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check_sms() -> CheckResult:
    if not settings.AT_API_KEY:
        return CheckResult("sms", False, "AT_API_KEY unset")
    try:
        import africastalking
        africastalking.initialize(settings.AT_USERNAME, settings.AT_API_KEY)
        _ = africastalking.Application.fetch_application_data()
        return CheckResult("sms", True, f"AT app reachable as {settings.AT_USERNAME}")
    except Exception as e:
        return CheckResult("sms", False, f"AT error: {e}")


def _check_hubspot() -> CheckResult:
    if not settings.HUBSPOT_ACCESS_TOKEN:
        return CheckResult("hubspot", False, "HUBSPOT_ACCESS_TOKEN unset")
    try:
        from hubspot import HubSpot
        client = HubSpot(access_token=settings.HUBSPOT_ACCESS_TOKEN)
        result = client.crm.contacts.basic_api.get_page(limit=1)
        return CheckResult("hubspot", True, f"HubSpot reachable, {len(result.results)} contact visible")
    except Exception as e:
        return CheckResult("hubspot", False, f"HubSpot error: {e}")


def _check_calcom() -> CheckResult:
    if not settings.CALCOM_API_KEY:
        return CheckResult("calcom", False, "CALCOM_API_KEY unset")
    import httpx
    try:
        r = httpx.get(
            f"{settings.CALCOM_BASE_URL}/v1/me",
            params={"apiKey": settings.CALCOM_API_KEY},
            timeout=10.0,
        )
        r.raise_for_status()
        return CheckResult("calcom", True, "Cal.com /v1/me reachable")
    except Exception as e:
        return CheckResult("calcom", False, f"Cal.com error: {e}")


def _check_langfuse() -> CheckResult:
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return CheckResult("langfuse", False, "LANGFUSE_* unset")
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        lf.trace(name="day0_smoke_test", metadata={"phase": "day0"})
        lf.flush()
        return CheckResult("langfuse", True, "Langfuse trace sent")
    except Exception as e:
        return CheckResult("langfuse", False, f"Langfuse error: {e}")


def _check_openrouter() -> CheckResult:
    if not settings.OPENROUTER_API_KEY:
        return CheckResult("openrouter", False, "OPENROUTER_API_KEY unset")
    try:
        from agent.llm import LLMClient
        r = LLMClient(tier="dev").complete(
            system="Reply with the single word OK.",
            user="ping",
            max_tokens=8,
            temperature=0.0,
        )
        return CheckResult("openrouter", True, f"model={r.model} reply={r.text.strip()!r}")
    except Exception as e:
        return CheckResult("openrouter", False, f"OpenRouter error: {e}")


def _check_resend() -> CheckResult:
    if not settings.RESEND_API_KEY:
        return CheckResult("resend", False, "RESEND_API_KEY unset")
    try:
        import httpx
        r = httpx.get(
            "https://api.resend.com/domains",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            timeout=10.0,
        )
        r.raise_for_status()
        return CheckResult("resend", True, f"Resend /domains reachable ({r.status_code})")
    except Exception as e:
        return CheckResult("resend", False, f"Resend error: {e}")


def _check_layoffs() -> CheckResult:
    try:
        from enrichment.layoffs import LayoffsIndex
        idx = LayoffsIndex.load()
        n_companies = len(idx.by_name)
        return CheckResult("layoffs", n_companies > 0, f"loaded {n_companies} companies")
    except Exception as e:
        return CheckResult("layoffs", False, f"Layoffs error: {e}")


def _check_crunchbase() -> CheckResult:
    try:
        from enrichment.crunchbase import CrunchbaseIndex
        idx = CrunchbaseIndex.load()
        n = len(idx.all)
        sample = idx.all[0].name if idx.all else "<empty>"
        return CheckResult("crunchbase", n > 0, f"loaded {n} records; first={sample!r}")
    except Exception as e:
        return CheckResult("crunchbase", False, f"Crunchbase error: {e}")


CHECKS: dict[str, Callable[[], CheckResult]] = {
    "resend": _check_resend,
    "sms": _check_sms,
    "hubspot": _check_hubspot,
    "calcom": _check_calcom,
    "langfuse": _check_langfuse,
    "openrouter": _check_openrouter,
    "layoffs": _check_layoffs,
    "crunchbase": _check_crunchbase,
}


def main(argv: list[str]) -> int:
    target = argv[1] if len(argv) > 1 else "all"
    names = list(CHECKS) if target == "all" else [target]
    results: list[CheckResult] = []
    for n in names:
        if n not in CHECKS:
            print(f"unknown check: {n}")
            return 2
        r = CHECKS[n]()
        results.append(r)
        mark = "[x]" if r.ok else "[ ]"
        print(f"{mark} {r.name:12} {r.detail}")
    failed = [r for r in results if not r.ok]
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
