"""Labeled eval harness for the autodraft LLM decision + auto-send gate.

Runs the REAL call_llm + validate_decision + auto_send_allowed pipeline
against a small set of synthetic, hand-labeled cases (autodraft_eval.json)
to catch prompt regressions and unsafe auto-sends before they hit a real
inbox. Never touches Mail.app or a real mailbox — only the LLM backends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from imail.autodraft import (
    auto_send_allowed,
    build_llm_prompt,
    call_llm,
    human_voice,
    validate_decision,
)

EVAL_CASES_PATH = Path(__file__).with_name("autodraft_eval.json")


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load labeled eval cases from the packaged JSON file (or an override path)."""
    return json.loads((path or EVAL_CASES_PATH).read_text())


def run_eval(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run each labeled case through the real decision pipeline and score it.

    A case FAILS if it would send when its `never_send` expectation is true,
    or if its `needs_reply`/`stakes` expectations (when given) don't match
    the LLM's decision. A case that errors out never sends, so it only fails
    if `never_send` was explicitly false (i.e. a send was actually expected).
    """
    results: list[dict[str, Any]] = []
    for case in cases:
        expect = case.get("expect", {})
        row: dict[str, Any] = {
            "case": case.get("case", "?"),
            "needs_reply": None,
            "stakes": None,
            "confidence": None,
            "action": "error",
            "unsafe_send": False,
            "passed": expect.get("never_send", True) is True,
            "reason": "",
        }
        try:
            prompt = build_llm_prompt(
                case.get("context", ""), case["sender"], case["subject"], case["body"]
            )
            decision = validate_decision(call_llm(prompt))
        except Exception as exc:
            row["reason"] = f"llm/validation error: {exc}"
            results.append(row)
            continue

        needs_reply = bool(decision.get("needs_reply"))
        interesting = bool(decision.get("interesting"))
        stakes = decision.get("stakes")
        confidence = float(decision.get("confidence", 0))
        reply_body = human_voice(str(decision.get("reply", "")))

        if not needs_reply or not interesting:
            action = "skip"
        elif auto_send_allowed(decision, bool(case.get("known")), False, reply_body):
            action = "send"
        else:
            action = "draft"

        unsafe_send = action == "send" and expect.get("never_send", True)

        passed = not unsafe_send
        if "needs_reply" in expect and needs_reply != expect["needs_reply"]:
            passed = False
        if "stakes" in expect and stakes != expect["stakes"]:
            passed = False

        row.update(
            needs_reply=needs_reply,
            stakes=stakes,
            confidence=confidence,
            action=action,
            unsafe_send=bool(unsafe_send),
            passed=passed,
            reason=decision.get("reason", ""),
        )
        results.append(row)

    return results


def format_eval_table(results: list[dict[str, Any]]) -> str:
    """Render the eval results as a human-readable table plus summary line."""
    header = f"{'case':<32} {'needs_reply':<12} {'stakes':<7} {'confidence':<11} {'action':<7} result"
    lines = [header]
    for r in results:
        conf = f"{r['confidence']:.2f}" if r["confidence"] is not None else "n/a"
        status = "PASS" if r["passed"] else "FAIL"
        lines.append(
            f"{r['case']:<32} {str(r['needs_reply']):<12} {str(r['stakes']):<7} "
            f"{conf:<11} {r['action']:<7} {status}"
        )
    passed = sum(1 for r in results if r["passed"])
    unsafe = sum(1 for r in results if r["unsafe_send"])
    lines.append(f"\n{passed}/{len(results)} passed, {unsafe} unsafe sends")
    return "\n".join(lines)
