"""Edge-case and property-based tests for imail.mail.

Complements tests/test_mail.py (owned separately — do not edit it here).
Mocks every OS/network boundary (subprocess.run, subprocess.Popen, `open -a Mail`,
textutil) exactly like test_mail.py; real tmp files/zipfile/email-module operations
on local temp paths are used directly since they are not OS/network boundaries.
"""

from __future__ import annotations

import random as random_module
import zipfile
from email import message_from_bytes
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from imail import mail

# --------------------------------------------------------------------------
# escape_applescript — property-based + boundary
# --------------------------------------------------------------------------


def _preceding_backslash_run(s: str, idx: int) -> int:
    """Length of the contiguous run of backslashes immediately before s[idx]."""
    j = idx - 1
    count = 0
    while j >= 0 and s[j] == "\\":
        count += 1
        j -= 1
    return count


@given(st.text(max_size=500))
@settings(max_examples=50, deadline=None)
def test_escape_applescript_every_quote_has_odd_backslash_prefix(value: str) -> None:
    out = mail.escape_applescript(value)
    for i, ch in enumerate(out):
        if ch == '"':
            assert _preceding_backslash_run(out, i) % 2 == 1


@given(st.text(max_size=500))
@settings(max_examples=50, deadline=None)
def test_escape_applescript_backslash_and_quote_counts_are_exact(value: str) -> None:
    out = mail.escape_applescript(value)
    n_bs = value.count("\\")
    n_q = value.count('"')
    assert out.count('"') == n_q
    assert out.count("\\") == 2 * n_bs + n_q


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),  # exclude lone surrogates
        max_size=500,
    )
)
@settings(max_examples=50, deadline=None)
def test_escape_applescript_manual_unescape_round_trips(value: str) -> None:
    out = mail.escape_applescript(value)
    recovered = out.replace('\\"', '"').replace("\\\\", "\\")
    assert recovered == value


ESCAPE_BOUNDARY_CASES = [
    ("empty", ""),
    ("only_backslashes", "\\" * 10),
    ("only_quotes", '"' * 10),
    ("alternating", '\\"' * 20),
    ("single_backslash", "\\"),
    ("single_quote", '"'),
    ("applescript_injection", '"; do shell script "rm -rf ~""'),
    ("escaped_tell_injection", '\\"; end tell; do shell script \\"'),
    ("sql_injection", "' OR '1'='1"),
    ("shell_injection", "$(rm -rf /)"),
    ("unicode_mixed", 'héllo "wörld" \\ 日本語'),
    ("emoji", '🚀🎉 "party" \\time'),
    ("rtl_arabic", 'مرحبا "كيف" \\ حالك'),
    ("rtl_hebrew", 'שלום "עולם" \\'),
    ("newlines", 'line1\n"line2"\nline3\\'),
    ("null_adjacent", 'a\x00"b\x00\\c'),
    ("very_long", ("x" * 25000) + '"' + ("\\" * 25000)),
]


@pytest.mark.parametrize("name,value", ESCAPE_BOUNDARY_CASES, ids=[c[0] for c in ESCAPE_BOUNDARY_CASES])
def test_escape_applescript_boundary_cases_do_not_crash_and_round_trip(name: str, value: str) -> None:
    out = mail.escape_applescript(value)
    assert out.count('"') == value.count('"')
    assert out.replace('\\"', '"').replace("\\\\", "\\") == value


def test_escape_applescript_empty_string_returns_empty() -> None:
    assert mail.escape_applescript("") == ""


def test_escape_applescript_no_special_chars_is_identity() -> None:
    assert mail.escape_applescript("plain text 123") == "plain text 123"


# --------------------------------------------------------------------------
# markdown_to_html
# --------------------------------------------------------------------------


def test_markdown_to_html_empty_string() -> None:
    html = mail.markdown_to_html("")
    assert "<body" in html
    assert "</html>" in html


def test_markdown_to_html_only_whitespace() -> None:
    html = mail.markdown_to_html("   \n   \n")
    assert "<h1>" not in html


def test_markdown_to_html_huge_input_does_not_crash() -> None:
    md = "Paragraph text. " * 1500  # ~24k chars
    html = mail.markdown_to_html(md)
    assert "Paragraph text." in html


def test_markdown_to_html_unicode_emoji_rtl() -> None:
    md = "# 日本語 🚀\n\nمرحبا שלום"
    html = mail.markdown_to_html(md)
    assert "日本語" in html
    assert "🚀" in html
    assert "مرحبا" in html
    assert "שלום" in html


def test_markdown_to_html_no_trailing_newline_closes_paragraph() -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html("Just one line no newline")
    assert "<p>" in html
    assert "</p>" in html


def test_markdown_to_html_consecutive_blank_lines_no_duplicate_close() -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html("Para1\n\n\n\nPara2")
    assert html.count("<p>") == 2
    assert html.count("</p>") == 2


def test_markdown_to_html_header_with_only_whitespace_after_marker_is_not_a_header() -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html("#   \nBody text")
    assert "<h1>" not in html


MALFORMED_MARKDOWN_FALLBACK_CASES = [
    ("unbalanced_backtick", "This has an `unterminated backtick"),
    ("unbalanced_bold", "This has **unterminated bold"),
    ("nested_headers", "### Deep header text"),
    ("header_then_more_hashes", "## ### looks nested"),
    ("only_header_no_body", "# Solo Header"),
    ("mixed_headers", "# H1\n## H2\n### H3\nplain"),
]


@pytest.mark.parametrize(
    "name,md", MALFORMED_MARKDOWN_FALLBACK_CASES, ids=[c[0] for c in MALFORMED_MARKDOWN_FALLBACK_CASES]
)
def test_markdown_to_html_fallback_malformed_cases_do_not_crash(name: str, md: str) -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html(md)
    assert "<html>" in html


def test_markdown_to_html_fallback_escapes_html_special_chars() -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html("Use <script>alert(1)</script> & \"quotes\"")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_markdown_to_html_fallback_h1_h2_h3_convert() -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html("# One\n## Two\n### Three")
    assert "<h1>One</h1>" in html
    assert "<h2>Two</h2>" in html
    assert "<h3>Three</h3>" in html


def test_markdown_to_html_fallback_h3_not_misdetected_as_h1_or_h2() -> None:
    with patch.dict("sys.modules", {"markdown_it": None}):
        html = mail.markdown_to_html("### Only H3")
    assert "<h1>" not in html
    assert "<h2>" not in html
    assert "<h3>Only H3</h3>" in html


# --------------------------------------------------------------------------
# humanize_text
# --------------------------------------------------------------------------

_HUMANIZE_ALPHABET = list("abcdefghijABCDEFGHIJ !.\n@/:") + ["🚀", "🎉", "☎", "✅", "➡"]


@given(st.text(alphabet=_HUMANIZE_ALPHABET, max_size=300))
@settings(max_examples=50, deadline=None)
def test_humanize_text_never_contains_double_bang(text: str) -> None:
    out = mail.humanize_text(text, typo_rate=0.0)
    assert "!!" not in out


@given(st.text(alphabet=_HUMANIZE_ALPHABET, max_size=300))
@settings(max_examples=50, deadline=None)
def test_humanize_text_always_strips_defined_emoji_ranges(text: str) -> None:
    out = mail.humanize_text(text, typo_rate=0.0)
    for ch in "🚀🎉☎✅➡":
        assert ch not in out


def test_humanize_text_empty_string() -> None:
    assert mail.humanize_text("", typo_rate=0.0) == ""


def test_humanize_text_only_whitespace_line_collapses_to_empty() -> None:
    assert mail.humanize_text("   ", typo_rate=0.0) == ""


def test_humanize_text_preserves_url_lines_exactly() -> None:
    raw = "Check this out:\nhttps://example.com/path?q=1&x=2\nBye."
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert "https://example.com/path?q=1&x=2" in out.splitlines()


def test_humanize_text_preserves_email_lines_exactly() -> None:
    raw = "Reach me at:\nme@corp.com\nThanks."
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert "me@corp.com" in out.splitlines()


def test_humanize_text_saturated_with_emojis_becomes_empty() -> None:
    raw = "🚀🎉☎✅➡🚀🎉"
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert out.strip() == ""


def test_humanize_text_strips_all_emoji_from_mixed_line() -> None:
    raw = "Hi 🚀 team 🎉, great work ➡ today ✅!"
    out = mail.humanize_text(raw, typo_rate=0.0)
    for ch in "🚀🎉➡✅":
        assert ch not in out


def test_humanize_text_five_separate_exclamations_capped() -> None:
    raw = "Wow! Cool! Great! Nice! Awesome!"
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert out.count("!") == 2
    assert "!!" not in out


def test_humanize_text_five_consecutive_exclamations_collapsed() -> None:
    raw = "Amazing!!!!! Truly."
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert "!!" not in out
    assert out.count("!") == 1


def test_humanize_text_many_short_lines_preserved_count() -> None:
    raw = "\n".join(f"line {i}" for i in range(500))
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert len(out.split("\n")) == 500


def test_humanize_text_one_huge_line_does_not_crash() -> None:
    raw = "word " * 10000  # ~50k chars
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert len(out) > 0


def test_humanize_text_rtl_arabic_structurally_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(random_module, "random", lambda: 0.99)
    raw = "مرحبا بكم في هذا النص"
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert out == raw  # no ASCII "I"/capital-letter branches apply to Arabic


def test_humanize_text_rtl_hebrew_structurally_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(random_module, "random", lambda: 0.99)
    raw = "שלום לכולם היום"
    out = mail.humanize_text(raw, typo_rate=0.0)
    assert out == raw


def test_humanize_text_signoff_best_regards_replaced() -> None:
    out = mail.humanize_text("See you soon.\nBest regards,\nAlice", typo_rate=0.0)
    assert "Thanks," in out
    assert "Best regards" not in out


def test_humanize_text_signoff_warm_regards_replaced() -> None:
    out = mail.humanize_text("Warm regards,\nBob", typo_rate=0.0)
    assert "Thanks," in out


def test_humanize_text_forced_high_random_makes_no_probabilistic_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(random_module, "random", lambda: 0.99)
    text = "Hello World, I like this."
    out = mail.humanize_text(text, typo_rate=0.0)
    assert out == text


def test_humanize_text_forced_low_random_triggers_all_probabilistic_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(random_module, "random", lambda: 0.0)
    text = "Hello World, I like this."
    out = mail.humanize_text(text, typo_rate=0.0)
    assert out == "hello World, i like this"


# --------------------------------------------------------------------------
# list_messages internal TSV parsing
# --------------------------------------------------------------------------


def _mock_run(stdout: str = "", stderr: str = "", returncode: int = 0):
    return patch(
        "imail.mail.subprocess.run",
        return_value=MagicMock(returncode=returncode, stdout=stdout, stderr=stderr),
    )


def test_list_messages_empty_stdout_returns_empty_list() -> None:
    with _mock_run(stdout=""):
        assert mail.list_messages() == []


def test_list_messages_skips_lines_with_fewer_than_four_fields() -> None:
    with _mock_run(stdout="1\tdate\tsender\n2\tonly\n"):
        assert mail.list_messages() == []


def test_list_messages_keeps_embedded_tabs_in_subject() -> None:
    with _mock_run(stdout="1\tMon Jan 1\talice@x.com\tSubject\twith\ttabs\n"):
        rows = mail.list_messages()
    assert rows == [
        {"index": "1", "date": "Mon Jan 1", "sender": "alice@x.com", "subject": "Subject\twith\ttabs"}
    ]


def test_list_messages_unicode_subject_and_sender() -> None:
    with _mock_run(stdout="1\tMon Jan 1\t日本語@x.com\t日本語の件名 🚀\n"):
        rows = mail.list_messages()
    assert rows[0]["sender"] == "日本語@x.com"
    assert rows[0]["subject"] == "日本語の件名 🚀"


def test_list_messages_subject_with_literal_backslash_n() -> None:
    with _mock_run(stdout="1\tMon Jan 1\talice@x.com\tSubject\\nwith literal backslash-n\n"):
        rows = mail.list_messages()
    assert rows[0]["subject"] == "Subject\\nwith literal backslash-n"


def test_list_messages_nonzero_returncode_empty_stderr_and_stdout_raises_sane_message() -> None:
    with _mock_run(stdout="", stderr="", returncode=1):
        with pytest.raises(RuntimeError, match="osascript failed"):
            mail.list_messages()


def test_list_messages_nonzero_returncode_prefers_stderr() -> None:
    with _mock_run(stdout="ignored", stderr="real error", returncode=1):
        with pytest.raises(RuntimeError, match="real error"):
            mail.list_messages()


def test_list_messages_multiple_valid_and_invalid_lines_mixed() -> None:
    stdout = "1\td1\ts1\tsub1\nbadline\n2\td2\ts2\tsub2\n\nnotab\n"
    with _mock_run(stdout=stdout):
        rows = mail.list_messages()
    assert len(rows) == 2
    assert rows[0]["subject"] == "sub1"
    assert rows[1]["subject"] == "sub2"


# --------------------------------------------------------------------------
# get_message_details internal parsing
# --------------------------------------------------------------------------


def test_get_message_details_parses_replied_and_attachment_flags() -> None:
    with _mock_run(stdout="true\t2\tHello body"):
        details = mail.get_message_details("acct", 1)
    assert details == {"body": "Hello body", "was_replied_to": True, "has_attachments": True}


def test_get_message_details_no_attachments() -> None:
    with _mock_run(stdout="false\t0\tHello body"):
        details = mail.get_message_details("acct", 1)
    assert details["has_attachments"] is False


def test_get_message_details_body_with_embedded_tabs_kept_intact() -> None:
    with _mock_run(stdout="false\t0\tBody\twith\ttabs"):
        details = mail.get_message_details("acct", 1)
    assert details["body"] == "Body\twith\ttabs"


def test_get_message_details_truncates_body_to_4000_chars() -> None:
    long_body = "x" * 5000
    with _mock_run(stdout=f"false\t0\t{long_body}"):
        details = mail.get_message_details("acct", 1)
    assert len(details["body"]) == 4000


def test_get_message_details_unicode_body() -> None:
    with _mock_run(stdout="false\t0\t日本語 🚀 مرحبا"):
        details = mail.get_message_details("acct", 1)
    assert details["body"] == "日本語 🚀 مرحبا"


def test_get_message_details_malformed_output_wrong_part_count_raises_with_raw_output() -> None:
    with _mock_run(stdout="only one field no tabs at all"):
        with pytest.raises(RuntimeError, match="unexpected output from Mail.app"):
            mail.get_message_details("acct", 1)


def test_get_message_details_malformed_output_too_many_would_be_parts_kept_as_three() -> None:
    # split("\t", 2) caps at 3 parts even with more tabs present — never raises for extra tabs.
    with _mock_run(stdout="true\t1\tbody\twith\tmore\ttabs"):
        details = mail.get_message_details("acct", 1)
    assert details["body"] == "body\twith\tmore\ttabs"


def test_get_message_details_nonzero_returncode_raises() -> None:
    with _mock_run(stdout="", stderr="boom", returncode=1):
        with pytest.raises(RuntimeError, match="boom"):
            mail.get_message_details("acct", 1)


# --------------------------------------------------------------------------
# is_known_correspondent
# --------------------------------------------------------------------------


def test_is_known_correspondent_empty_string_returns_false_without_subprocess() -> None:
    with patch("imail.mail.subprocess.run") as mock_run:
        assert mail.is_known_correspondent("") is False
    mock_run.assert_not_called()


def test_is_known_correspondent_nonzero_returncode_returns_false_not_raise() -> None:
    with _mock_run(stdout="true", returncode=1):
        assert mail.is_known_correspondent("a@b.com") is False


def test_is_known_correspondent_true_on_match() -> None:
    with _mock_run(stdout="true"):
        assert mail.is_known_correspondent("a@b.com") is True


def test_is_known_correspondent_false_on_no_match() -> None:
    with _mock_run(stdout="false"):
        assert mail.is_known_correspondent("a@b.com") is False


def test_is_known_correspondent_weird_casing_and_whitespace_still_parses_true() -> None:
    with _mock_run(stdout="  TRUE  \n"):
        assert mail.is_known_correspondent("a@b.com") is True


def test_is_known_correspondent_passes_raw_email_via_argv_not_interpolated() -> None:
    payload = 'inject"er@x.com'
    with _mock_run(stdout="false") as _:
        with patch("imail.mail.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="false", stderr="")
            mail.is_known_correspondent(payload)
    args = mock_run.call_args[0][0]
    assert payload in args
    script = mock_run.call_args.kwargs.get("input", "")
    assert payload not in script  # never string-interpolated into the AppleScript source


def test_is_known_correspondent_unicode_email() -> None:
    with patch("imail.mail.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="true", stderr="")
        assert mail.is_known_correspondent("日本語@example.jp") is True
    assert "日本語@example.jp" in mock_run.call_args[0][0]


# --------------------------------------------------------------------------
# send_message / save_silent_draft / create_eml_draft
# --------------------------------------------------------------------------


def _make_files(tmp_path: Path, *names: str) -> list[str]:
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_text(f"content of {name}")
        paths.append(str(p))
    return paths


class TestSendMessageEdgeCases:
    def test_empty_cc_omits_cc_block(self) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(to="a@b.com", subject="S", body="B", from_addr="", cc="", is_markdown=False)
        assert "make new cc recipient" not in mock_run.call_args[0][0]

    def test_attachments_none_and_empty_list_produce_identical_scripts(self) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(to="a@b.com", subject="S", body="B", from_addr="", attachments=None, is_markdown=False)
            script_none = mock_run.call_args[0][0]
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(to="a@b.com", subject="S", body="B", from_addr="", attachments=[], is_markdown=False)
            script_empty = mock_run.call_args[0][0]
        assert script_none == script_empty
        assert "make new attachment" not in script_none

    def test_missing_attachment_raises_before_any_subprocess_call(self) -> None:
        with patch.object(mail, "run_as") as mock_run_as, patch("imail.mail.subprocess.run") as mock_sub:
            with pytest.raises(FileNotFoundError, match="Attachment file not found"):
                mail.send_message(
                    to="a@b.com",
                    subject="S",
                    body="B",
                    from_addr="",
                    attachments=["/no/such/file.pdf"],
                    is_markdown=True,
                )
        mock_run_as.assert_not_called()
        mock_sub.assert_not_called()

    def test_zip_attachments_true_with_multiple_files_creates_single_zip(self, tmp_path: Path) -> None:
        files = _make_files(tmp_path, "a.txt", "b.txt")
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(
                to="a@b.com",
                subject="S",
                body="B",
                from_addr="",
                attachments=files,
                zip_attachments=True,
                is_markdown=False,
            )
        script = mock_run.call_args[0][0]
        assert script.count("make new attachment") == 1
        assert "attachments.zip" in script
        assert "a.txt" not in script
        assert "b.txt" not in script

    @pytest.mark.parametrize(
        "subject,expected",
        [
            ("Re: Hello", "Re: Hello"),
            ("RE: HELLO THERE", "RE: HELLO THERE"),
            ("re: already lower", "re: already lower"),
            ("REMINDER Now", "reminder now"),
            ("Plain Subject Line", "plain subject line"),
            ("", ""),
        ],
    )
    def test_subject_re_prefix_preserved_else_lowercased(self, subject: str, expected: str) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(to="a@b.com", subject=subject, body="B", from_addr="", is_markdown=False)
        script = mock_run.call_args[0][0]
        assert f'subject:"{mail.escape_applescript(expected)}"' in script

    def test_humanize_true_calls_humanize_text(self) -> None:
        with patch.object(mail, "run_as", return_value="OK"), patch.object(
            mail, "humanize_text", return_value="humanized"
        ) as mock_humanize:
            mail.send_message(to="a@b.com", subject="S", body="raw body", from_addr="", humanize=True, is_markdown=False)
        mock_humanize.assert_called_once()
        assert mock_humanize.call_args[0][0] == "raw body"

    def test_humanize_false_does_not_call_humanize_text(self) -> None:
        with patch.object(mail, "run_as", return_value="OK"), patch.object(mail, "humanize_text") as mock_humanize:
            mail.send_message(to="a@b.com", subject="S", body="raw body", from_addr="", humanize=False, is_markdown=False)
        mock_humanize.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [
            '"; do shell script "rm -rf ~""',
            '\\"; end tell; do shell script \\"',
            "' OR '1'='1",
            'plain "quoted" name',
        ],
        ids=["applescript_injection", "escaped_tell", "sql_like", "plain_quoted"],
    )
    def test_injection_payloads_in_to_field_are_escaped_in_script(self, payload: str) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(to=payload, subject="S", body="B", from_addr="", is_markdown=False)
        script = mock_run.call_args[0][0]
        assert mail.escape_applescript(payload) in script

    def test_unicode_injection_in_subject_and_body_escaped(self) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(
                to="a@b.com",
                subject='日本語 "件名"',
                body='本文 \\ "テスト"',
                from_addr="",
                is_markdown=False,
            )
        script = mock_run.call_args[0][0]
        assert mail.escape_applescript('日本語 "件名"'.lower()) in script
        assert mail.escape_applescript('本文 \\ "テスト"') in script


class TestSaveSilentDraftEdgeCases:
    def test_empty_cc_omits_cc_block(self) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.save_silent_draft(to="a@b.com", subject="S", body="B", from_addr="", cc="")
        assert "make new cc recipient" not in mock_run.call_args[0][0]

    def test_missing_attachment_raises_before_run_as(self) -> None:
        with patch.object(mail, "run_as") as mock_run_as:
            with pytest.raises(FileNotFoundError, match="Attachment file not found"):
                mail.save_silent_draft(
                    to="a@b.com", subject="S", body="B", from_addr="", attachments=["/no/such/file.pdf"]
                )
        mock_run_as.assert_not_called()

    def test_humanize_true_calls_humanize_text(self) -> None:
        with patch.object(mail, "run_as", return_value="OK"), patch.object(
            mail, "humanize_text", return_value="humanized"
        ) as mock_humanize:
            mail.save_silent_draft(to="a@b.com", subject="S", body="raw", from_addr="", humanize=True)
        mock_humanize.assert_called_once_with("raw")

    @pytest.mark.parametrize(
        "subject,expected",
        [("Re: Ping", "Re: Ping"), ("Loud Subject", "loud subject")],
    )
    def test_subject_re_prefix_rule(self, subject: str, expected: str) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.save_silent_draft(to="a@b.com", subject=subject, body="B", from_addr="")
        script = mock_run.call_args[0][0]
        assert f'subject:"{mail.escape_applescript(expected)}"' in script

    def test_injection_payload_in_from_addr_escaped(self) -> None:
        payload = '"; do shell script "rm -rf ~""'
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.save_silent_draft(to="a@b.com", subject="S", body="B", from_addr=payload)
        script = mock_run.call_args[0][0]
        assert mail.escape_applescript(payload) in script


class TestCreateEmlDraftEdgeCases:
    def test_open_in_mail_true_calls_open_subprocess(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_sub:
            mail.create_eml_draft(to="a@b.com", subject="S", body="B", from_addr="", open_in_mail=True)
        mock_sub.assert_called_once()
        assert mock_sub.call_args[0][0][:3] == ["open", "-a", "Mail"]

    def test_open_in_mail_false_does_not_call_subprocess(self) -> None:
        with patch("subprocess.run") as mock_sub:
            result = mail.create_eml_draft(to="a@b.com", subject="S", body="B", from_addr="", open_in_mail=False)
        mock_sub.assert_not_called()
        assert "OK draft created at" in result

    def test_eml_headers_roundtrip_via_email_module(self) -> None:
        with patch("subprocess.run") as mock_sub:
            result = mail.create_eml_draft(
                to="alice@x.com",
                subject="Hello There",
                body="Body text",
                from_addr="me@corp.com",
                cc="cc@corp.com",
                open_in_mail=False,
            )
        mock_sub.assert_not_called()
        eml_path = Path(result.split("OK draft created at ", 1)[1])
        parsed = message_from_bytes(eml_path.read_bytes())
        assert parsed["Subject"] == "hello there"
        assert parsed["To"] == "alice@x.com"
        assert parsed["From"] == "me@corp.com"
        assert parsed["Cc"] == "cc@corp.com"

    def test_eml_re_prefixed_subject_not_lowercased(self) -> None:
        with patch("subprocess.run"):
            result = mail.create_eml_draft(
                to="a@b.com", subject="RE: Keep Case", body="B", from_addr="", open_in_mail=False
            )
        eml_path = Path(result.split("OK draft created at ", 1)[1])
        parsed = message_from_bytes(eml_path.read_bytes())
        assert parsed["Subject"] == "RE: Keep Case"

    def test_missing_attachment_raises_before_writing_eml(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_sub:
            with pytest.raises(FileNotFoundError, match="Attachment file not found"):
                mail.create_eml_draft(
                    to="a@b.com",
                    subject="S",
                    body="B",
                    from_addr="",
                    attachments=["/no/such/file.pdf"],
                    open_in_mail=False,
                )
        mock_sub.assert_not_called()

    def test_zip_attachments_true_bundles_multiple_files_in_one_attachment(self, tmp_path: Path) -> None:
        files = _make_files(tmp_path, "one.txt", "two.txt")
        with patch("subprocess.run"):
            result = mail.create_eml_draft(
                to="a@b.com",
                subject="S",
                body="B",
                from_addr="",
                attachments=files,
                zip_attachments=True,
                open_in_mail=False,
            )
        eml_path = Path(result.split("OK draft created at ", 1)[1])
        parsed = message_from_bytes(eml_path.read_bytes())
        attachment_names = [
            part.get_filename() for part in parsed.walk() if part.get_content_disposition() == "attachment"
        ]
        assert attachment_names == ["attachments.zip"]

    def test_humanize_true_calls_humanize_text(self) -> None:
        with patch("subprocess.run"), patch.object(mail, "humanize_text", return_value="clean") as mock_humanize:
            mail.create_eml_draft(to="a@b.com", subject="S", body="raw body", from_addr="", humanize=True, open_in_mail=False)
        mock_humanize.assert_called_once_with("raw body")

    def test_is_markdown_true_adds_html_alternative_part(self) -> None:
        with patch("subprocess.run"):
            result = mail.create_eml_draft(
                to="a@b.com", subject="S", body="# Title", from_addr="", is_markdown=True, open_in_mail=False
            )
        eml_path = Path(result.split("OK draft created at ", 1)[1])
        parsed = message_from_bytes(eml_path.read_bytes())
        html_parts = [p for p in parsed.walk() if p.get_content_type() == "text/html"]
        assert len(html_parts) == 1

    def test_is_markdown_false_has_no_html_alternative_part(self) -> None:
        with patch("subprocess.run"):
            result = mail.create_eml_draft(
                to="a@b.com", subject="S", body="Plain body", from_addr="", is_markdown=False, open_in_mail=False
            )
        eml_path = Path(result.split("OK draft created at ", 1)[1])
        parsed = message_from_bytes(eml_path.read_bytes())
        html_parts = [p for p in parsed.walk() if p.get_content_type() == "text/html"]
        assert html_parts == []

    def test_no_to_cc_from_omits_those_headers(self) -> None:
        with patch("subprocess.run"):
            result = mail.create_eml_draft(to="", subject="S", body="B", from_addr="", cc="", open_in_mail=False)
        eml_path = Path(result.split("OK draft created at ", 1)[1])
        parsed = message_from_bytes(eml_path.read_bytes())
        assert parsed["To"] is None
        assert parsed["From"] is None
        assert parsed["Cc"] is None
