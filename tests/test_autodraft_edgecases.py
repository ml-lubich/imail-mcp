"""Edge-case tests for imail autodraft + autodraft_eval.

Companion to test_autodraft.py / test_autodraft_eval.py — this file targets
boundaries and malformed input those files don't already cover: unicode,
extreme lengths, regex-special characters, JSON extraction fuzzing, and the
full validate_decision / auto_send_allowed gate matrices. Every network/OS
boundary (subprocess, urllib, Mail.app) stays mocked, matching the existing
test conventions.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from imail.autodraft import (
    INTENT_CONFIRMATION,
    INTENT_DIRECT_INQUIRY,
    INTENT_RECRUITER,
    INTENT_SKIP,
    MAX_AUTO_SEND_LEN,
    MIN_AUTO_SEND_CONFIDENCE,
    _extract_json,
    _normalize_subject,
    _seen_key,
    auto_send_allowed,
    classify_intent,
    matches_skip_patterns,
    validate_decision,
)
from imail.autodraft_eval import load_cases, run_eval

# ---------------------------------------------------------------------------
# matches_skip_patterns
# ---------------------------------------------------------------------------


def test_matches_skip_patterns_empty_sender_and_subject():
    assert matches_skip_patterns("", "") is False


def test_matches_skip_patterns_unicode_no_match():
    assert matches_skip_patterns("友人@example.com", "晩ご飯どう? 🍜") is False


def test_matches_skip_patterns_emoji_with_skip_keyword():
    assert matches_skip_patterns("friend@example.com", "🎉 weekly newsletter 🎉") is True


def test_matches_skip_patterns_extremely_long_subject_still_matches():
    subject = "x" * 10_000 + " weekly newsletter"
    assert matches_skip_patterns("friend@example.com", subject) is True


def test_matches_skip_patterns_extremely_long_subject_no_match_is_fast_and_false():
    subject = "x" * 10_000
    assert matches_skip_patterns("friend@example.com", subject) is False


@pytest.mark.parametrize(
    "sender,subject",
    [
        ("((()))@evil.com", "a.*b"),  # regex metachars as literal sender data
        ("friend@example.com", "$100 [urgent] (call now)"),
        ("friend+tag@example.com", "re: .* matches everything?"),
    ],
)
def test_matches_skip_patterns_regex_metachars_as_literal_data_no_match(sender, subject):
    # sender/subject are matched AGAINST fixed patterns, never compiled into one —
    # metacharacters in the data must not be treated as regex syntax nor crash.
    assert matches_skip_patterns(sender, subject) is False


def test_matches_skip_patterns_regex_metachars_in_subject_still_matches_real_pattern():
    assert matches_skip_patterns("friend@example.com", "weekly round(up) special!") is True


@pytest.mark.parametrize("subject", ["NEWSLETTER", "newsletter", "NewsLetter", "nEwSlEtTeR"])
def test_matches_skip_patterns_case_insensitive_subject(subject):
    assert matches_skip_patterns("friend@example.com", f"our {subject} digest") is True


@pytest.mark.parametrize("sender", ["NO-REPLY@x.com", "no-reply@x.com", "No-Reply@x.com"])
def test_matches_skip_patterns_case_insensitive_sender(sender):
    assert matches_skip_patterns(sender, "hi") is True


# ---------------------------------------------------------------------------
# classify_intent
# ---------------------------------------------------------------------------


def test_classify_intent_empty_everything_is_skip():
    assert classify_intent("", "", "") == INTENT_SKIP


def test_classify_intent_unicode_fields_default_skip():
    assert classify_intent("友人@example.com", "こんにちは", "元気ですか") == INTENT_SKIP


def test_classify_intent_unicode_recruiter_keyword_still_detected():
    assert classify_intent("recruiter@example.com", "role opportunity 🚀", "") == INTENT_RECRUITER


def test_classify_intent_long_snippet_signal_is_read():
    snippet = "x" * 10_000 + " any update on this?"
    assert classify_intent("a@b.com", "hi", snippet) == INTENT_DIRECT_INQUIRY


def test_classify_intent_empty_snippet_relies_on_subject_only():
    assert classify_intent("a@b.com", "sounds good", "") == INTENT_CONFIRMATION
    assert classify_intent("a@b.com", "no signal here", "") == INTENT_SKIP


def test_classify_intent_confirmation_beats_recruiter_signal_in_snippet():
    # subject says confirmation, snippet says recruiter — confirmation is checked
    # first in the source, so it wins regardless of the snippet.
    result = classify_intent("friend@example.com", "sounds good", "btw are you hiring for a role?")
    assert result == INTENT_CONFIRMATION


def test_classify_intent_recruiter_beats_inquiry_signal_in_same_subject():
    # "job opportunity?" carries both a recruiter keyword and a '?' inquiry marker —
    # recruiter is checked before inquiry in the source, so it wins.
    assert classify_intent("someone@example.com", "job opportunity?", "") == INTENT_RECRUITER


def test_classify_intent_skip_patterns_checked_before_any_signal():
    # sender matches a skip pattern even though the subject also reads as a confirmation
    assert classify_intent("no-reply@example.com", "sounds good, see you then") == INTENT_SKIP


@pytest.mark.parametrize(
    "sender,subject,snippet,expected",
    [
        ("a@b.com", "", "", INTENT_SKIP),
        ("a@b.com", "does that work for you?", "", INTENT_CONFIRMATION),
        ("a@b.com", "got it thanks", "", INTENT_CONFIRMATION),
        ("recruiter@example.com", "W2 contract rate discussion", "", INTENT_RECRUITER),
        ("a@b.com", "when can we talk?", "", INTENT_DIRECT_INQUIRY),
        ("a@b.com", "no question or keyword at all", "", INTENT_SKIP),
    ],
)
def test_classify_intent_boundary_table(sender, subject, snippet, expected):
    assert classify_intent(sender, subject, snippet) == expected


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_json_missing_closing_brace():
    assert _extract_json('{"a": 1') is None


def test_extract_json_extra_text_before_and_after():
    assert _extract_json('here is your answer: {"a": 1} thanks!') == {"a": 1}


def test_extract_json_nested_braces_inside_string_value():
    assert _extract_json('{"a": "b{c}d"}') == {"a": "b{c}d"}


def test_extract_json_unicode_inside_string_value():
    assert _extract_json('{"reply": "元気ですか 🍜"}') == {"reply": "元気ですか 🍜"}


def test_extract_json_empty_string_input():
    assert _extract_json("") is None


def test_extract_json_no_braces_at_all_returns_none_not_raise():
    assert _extract_json("just plain text, no json here") is None
    assert _extract_json("[1, 2, 3]") is None  # bare array: no '{' present at all


def test_extract_json_multiple_objects_concatenated_is_invalid_and_returns_none():
    # first-'{' to last-'}' spans both objects with a gap between them — not valid JSON
    assert _extract_json('{"a": 1} {"b": 2}') is None


def test_extract_json_deeply_nested_structure():
    nested = {"a": {"b": {"c": {"d": [1, 2, {"e": "f"}]}}}}
    assert _extract_json(json.dumps(nested)) == nested


def test_extract_json_bare_number_returns_none():
    assert _extract_json("42") is None


def test_extract_json_decoy_brace_before_real_object_breaks_extraction():
    # documents actual (fragile) first-'{'/last-'}' slicing behavior: an earlier,
    # unrelated brace defeats extraction of the real JSON object that follows.
    # Fails safe either way — call_llm falls through to the next backend / raises.
    text = 'note: {use braces} then {"a": 1}'
    assert _extract_json(text) is None


def test_extract_json_quoted_string_literal_is_not_special_cased():
    # a bare JSON string containing brace characters is not itself an object, but
    # the naive first-'{'/last-'}' slice extracts an (empty) dict from inside it.
    # Documents actual behavior; downstream validate_decision still fails closed
    # on the resulting {} since none of the required keys are present.
    result = _extract_json('"{}"')
    assert result == {}
    with pytest.raises(ValueError):
        validate_decision(result)


def test_extract_json_strips_code_fence_and_recovers_dict():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


_SAFE_CHARS = st.characters(
    exclude_characters='{}"\\',
    exclude_categories=("Cs", "Cc"),
    max_codepoint=0x1F600,
)
_SAFE_TEXT = st.text(alphabet=_SAFE_CHARS, max_size=10)
_JSON_SCALAR = st.one_of(
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    _SAFE_TEXT,
    st.none(),
)


@settings(max_examples=50, deadline=None)
@given(
    data=st.dictionaries(
        keys=st.text(alphabet=_SAFE_CHARS, min_size=1, max_size=8),
        values=_JSON_SCALAR,
        max_size=5,
    ),
    prefix=st.text(alphabet=_SAFE_CHARS, max_size=15),
    suffix=st.text(alphabet=_SAFE_CHARS, max_size=15),
)
def test_extract_json_hypothesis_recovers_embedded_dict(data, prefix, suffix):
    """A valid JSON object embedded in arbitrary brace-free surrounding text is
    always recovered exactly, regardless of prefix/suffix junk."""
    blob = json.dumps(data)
    text = f"{prefix}{blob}{suffix}"
    assert _extract_json(text) == data


# ---------------------------------------------------------------------------
# validate_decision — fail-closed safety gate
# ---------------------------------------------------------------------------


def _base_decision(**overrides):
    base = {
        "needs_reply": True,
        "interesting": True,
        "stakes": "low",
        "confidence": 0.9,
        "reply": "sounds good",
    }
    base.update(overrides)
    return base


def test_validate_decision_none_input_raises():
    with pytest.raises(ValueError):
        validate_decision(None)


@pytest.mark.parametrize("bad", [[], "a string", 5, 5.0, True, ()])
def test_validate_decision_non_dict_input_raises(bad):
    with pytest.raises(ValueError):
        validate_decision(bad)


def test_validate_decision_empty_dict_raises():
    with pytest.raises(ValueError, match="needs_reply"):
        validate_decision({})


def test_validate_decision_extra_unexpected_keys_are_ignored_not_rejected():
    d = _base_decision(unexpected_field="whatever", another=123)
    assert validate_decision(d) is d


@pytest.mark.parametrize("key", ["needs_reply", "interesting"])
@pytest.mark.parametrize("bad_value", ["true", "false", 1, 0, None, "yes"])
def test_validate_decision_bool_fields_reject_wrong_type(key, bad_value):
    with pytest.raises(ValueError, match=key):
        validate_decision(_base_decision(**{key: bad_value}))


@pytest.mark.parametrize("key", ["needs_reply", "interesting"])
def test_validate_decision_bool_fields_missing_key_raises(key):
    d = _base_decision()
    del d[key]
    with pytest.raises(ValueError, match=key):
        validate_decision(d)


@pytest.mark.parametrize("value", [True, False])
def test_validate_decision_bool_fields_accept_actual_booleans(value):
    assert validate_decision(_base_decision(needs_reply=value, interesting=value))["needs_reply"] == value


@pytest.mark.parametrize(
    "confidence,valid",
    [
        (-0.0001, False),
        (0.0, True),
        (0.5, True),
        (0.9499999, True),
        (0.95, True),
        (0.9500001, True),
        (1.0, True),
        (1.0001, False),
        ("0.95", False),  # numeric-looking string is still rejected
        (True, False),  # bool is a subclass of int but must be rejected
        (False, False),
        (None, False),
    ],
)
def test_validate_decision_confidence_boundaries(confidence, valid):
    d = _base_decision(confidence=confidence)
    if valid:
        assert validate_decision(d)["confidence"] == confidence
    else:
        with pytest.raises(ValueError, match="confidence"):
            validate_decision(d)


def test_validate_decision_confidence_missing_key_raises():
    d = _base_decision()
    del d["confidence"]
    with pytest.raises(ValueError, match="confidence"):
        validate_decision(d)


@pytest.mark.parametrize("stakes", ["low", "high"])
def test_validate_decision_stakes_accepts_exact_lowercase(stakes):
    assert validate_decision(_base_decision(stakes=stakes))["stakes"] == stakes


@pytest.mark.parametrize("stakes", ["Low", "LOW", "High", "medium", "", None, 1, ["low"]])
def test_validate_decision_stakes_rejects_anything_else(stakes):
    with pytest.raises(ValueError, match="stakes"):
        validate_decision(_base_decision(stakes=stakes))


def test_validate_decision_stakes_missing_key_raises():
    d = _base_decision()
    del d["stakes"]
    with pytest.raises(ValueError, match="stakes"):
        validate_decision(d)


@pytest.mark.parametrize("reply", [5, 5.0, ["a"], {"nested": "dict"}, True, None])
def test_validate_decision_reply_rejects_non_string(reply):
    with pytest.raises(ValueError, match="reply"):
        validate_decision(_base_decision(reply=reply))


def test_validate_decision_reply_accepts_empty_string():
    assert validate_decision(_base_decision(reply=""))["reply"] == ""


def test_validate_decision_reply_missing_key_raises_fail_closed():
    """Regression test for the fix in autodraft.py:validate_decision — a missing
    `reply` key used to silently default to "" (isinstance("", str) is True),
    unlike every other required field, which raises when its key is absent.
    A malformed LLM response missing `reply` entirely must fail closed too,
    not flow through as a valid empty-body decision."""
    d = _base_decision()
    del d["reply"]
    with pytest.raises(ValueError, match="reply"):
        validate_decision(d)


# ---------------------------------------------------------------------------
# auto_send_allowed — full boundary matrix, one gate flipped at a time
# ---------------------------------------------------------------------------


def _passing_decision(**overrides):
    base = {"confidence": 0.99, "stakes": "low", "intent": "confirmation"}
    base.update(overrides)
    return base


def test_auto_send_allowed_all_gates_passing():
    assert auto_send_allowed(_passing_decision(), known=True, has_attachments=False, reply_body="ok") is True


def test_auto_send_allowed_all_gates_failing():
    decision = _passing_decision(confidence=0.1, stakes="high", intent=INTENT_RECRUITER)
    assert auto_send_allowed(decision, known=False, has_attachments=True, reply_body="x" * 500) is False


@pytest.mark.parametrize(
    "confidence,expected",
    [
        (MIN_AUTO_SEND_CONFIDENCE - 0.0001, False),
        (MIN_AUTO_SEND_CONFIDENCE, True),  # boundary is >= in the source
        (MIN_AUTO_SEND_CONFIDENCE + 0.0001, True),
    ],
)
def test_auto_send_allowed_confidence_gate_boundary(confidence, expected):
    decision = _passing_decision(confidence=confidence)
    assert auto_send_allowed(decision, known=True, has_attachments=False, reply_body="ok") is expected


def test_auto_send_allowed_stakes_gate_just_passing_and_failing():
    assert auto_send_allowed(_passing_decision(stakes="low"), True, False, "ok") is True
    assert auto_send_allowed(_passing_decision(stakes="high"), True, False, "ok") is False


def test_auto_send_allowed_known_correspondent_gate():
    assert auto_send_allowed(_passing_decision(), known=True, has_attachments=False, reply_body="ok") is True
    assert auto_send_allowed(_passing_decision(), known=False, has_attachments=False, reply_body="ok") is False


def test_auto_send_allowed_attachments_gate():
    assert auto_send_allowed(_passing_decision(), True, has_attachments=False, reply_body="ok") is True
    assert auto_send_allowed(_passing_decision(), True, has_attachments=True, reply_body="ok") is False


def test_auto_send_allowed_recruiter_intent_gate():
    assert auto_send_allowed(_passing_decision(intent="confirmation"), True, False, "ok") is True
    assert auto_send_allowed(_passing_decision(intent=INTENT_RECRUITER), True, False, "ok") is False


@pytest.mark.parametrize(
    "length,expected",
    [
        (MAX_AUTO_SEND_LEN - 1, True),
        (MAX_AUTO_SEND_LEN, True),  # boundary is <= in the source
        (MAX_AUTO_SEND_LEN + 1, False),
    ],
)
def test_auto_send_allowed_reply_length_boundary(length, expected):
    body = "x" * length
    assert auto_send_allowed(_passing_decision(), True, False, body) is expected


def test_auto_send_allowed_confidence_as_string_still_coerces_via_float_call():
    # decision.get("confidence", 0) is passed through float(); a validated decision
    # always has a real float by the time it reaches here, but the gate itself
    # tolerates a numeric string rather than crashing.
    assert auto_send_allowed(_passing_decision(confidence="0.99"), True, False, "ok") is True


# ---------------------------------------------------------------------------
# _normalize_subject
# ---------------------------------------------------------------------------


def test_normalize_subject_empty_string():
    assert _normalize_subject("") == ""


def test_normalize_subject_strips_deeply_stacked_prefixes():
    assert _normalize_subject("Re: Re: Re: Fwd: RE: hello") == "hello"


def test_normalize_subject_mixed_prefix_forms():
    assert _normalize_subject("Fwd: Re: fw: catch up") == "catch up"


def test_normalize_subject_unicode_body_preserved():
    assert _normalize_subject("Re: 元気ですか") == "元気ですか"


def test_normalize_subject_unicode_prefix_not_stripped():
    # "Ré:" isn't an ASCII "re" match — the accented form passes through untouched.
    assert _normalize_subject("Ré: hello") == "ré: hello"


def test_normalize_subject_leading_trailing_whitespace_stripped():
    assert _normalize_subject("   Re: hello   ") == "hello"


def test_normalize_subject_only_prefix_no_remainder():
    assert _normalize_subject("Re:") == ""
    assert _normalize_subject("  Fwd:  ") == ""


def test_normalize_subject_collapses_internal_whitespace():
    assert _normalize_subject("Re:   lots   of    space") == "lots of space"


# ---------------------------------------------------------------------------
# _seen_key
# ---------------------------------------------------------------------------


def test_seen_key_recipient_case_is_normalized():
    assert _seen_key("acct@x.com", "Friend@Example.COM", "hi") == _seen_key("acct@x.com", "friend@example.com", "hi")


def test_seen_key_account_case_is_not_normalized():
    # documents actual behavior: only the recipient is lowercased, not the account
    assert _seen_key("ACCT@x.com", "f@x.com", "hi") != _seen_key("acct@x.com", "f@x.com", "hi")


def test_seen_key_whitespace_and_prefix_casing_in_subject_collapse_to_same_key():
    a = _seen_key("acct@x.com", "f@x.com", "Re:   Meeting   Tomorrow")
    b = _seen_key("acct@x.com", "f@x.com", "  meeting tomorrow  ")
    assert a == b


def test_seen_key_unicode_account_and_recipient():
    key = _seen_key("私@example.com", "友人@example.com", "hi")
    assert "私@example.com" in key
    assert "友人@example.com" in key


def test_seen_key_empty_subject():
    key = _seen_key("acct@x.com", "f@x.com", "")
    assert key == "acct@x.com|f@x.com|"


# ---------------------------------------------------------------------------
# autodraft_eval.py
# ---------------------------------------------------------------------------


def _decision(**overrides):
    base = {
        "needs_reply": True,
        "interesting": True,
        "stakes": "low",
        "intent": "confirmation",
        "confidence": 0.97,
        "reply": "sounds good",
        "reason": "trivial",
        "learn": [],
    }
    base.update(overrides)
    return base


def test_load_cases_missing_file_raises_filenotfounderror(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cases(tmp_path / "does_not_exist.json")


def test_load_cases_malformed_json_raises_decode_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not: valid json,,,")
    with pytest.raises(json.JSONDecodeError):
        load_cases(bad)


_CASE_KNOWN_CONFIDENT_BUT_EXPECTED_NEVER_SEND = {
    "case": "friend_asks_but_marked_never_send",
    "sender": "friend@example.com",
    "subject": "you free to chat about the role?",
    "body": "hey, got a sec to talk about a role?",
    "context": "",
    "known": True,
    "expect": {"never_send": True},
}


def test_run_eval_fails_when_unsafe_send_occurs_despite_no_needs_reply_or_stakes_expectation():
    """A case expects never_send=True (no needs_reply/stakes expectation given), but
    the decision is confident/low-stakes/known enough to actually auto-send.
    The harness must flag this as a real FAIL, not let the absence of other
    expectations wave it through."""
    with patch("imail.autodraft_eval.call_llm", return_value=_decision(confidence=0.99, stakes="low")):
        results = run_eval([_CASE_KNOWN_CONFIDENT_BUT_EXPECTED_NEVER_SEND])
    assert results[0]["action"] == "send"
    assert results[0]["unsafe_send"] is True
    assert results[0]["passed"] is False


def test_run_eval_needs_reply_and_stakes_both_mismatched_fails():
    case = {
        "case": "double_mismatch",
        "sender": "a@b.com",
        "subject": "hi",
        "body": "hi",
        "context": "",
        "known": True,
        "expect": {"needs_reply": False, "stakes": "high"},
    }
    with patch("imail.autodraft_eval.call_llm", return_value=_decision(needs_reply=True, stakes="low")):
        results = run_eval([case])
    assert results[0]["passed"] is False


def test_run_eval_validation_error_from_malformed_llm_output_is_safe_error_action():
    case = {
        "case": "malformed_llm_output",
        "sender": "a@b.com",
        "subject": "hi",
        "body": "hi",
        "context": "",
        "known": True,
        "expect": {"never_send": True},
    }
    with patch("imail.autodraft_eval.call_llm", return_value=_decision(stakes="LOW")):  # invalid case
        results = run_eval([case])
    assert results[0]["action"] == "error"
    assert results[0]["unsafe_send"] is False
    assert results[0]["passed"] is True
