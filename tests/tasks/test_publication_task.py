# SPDX-License-Identifier: GPL-3.0-only

import logging
from contextlib import contextmanager, nullcontext
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace as otel_trace

from publisher.keys import KeyNotFoundError, KeyUnavailableError, TokenVerificationError
from publisher.publications import (
    AdapterIntegrationError,
    OfflineTagInvalidError,
    OfflineTagMissingError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
)
from publisher.tasks import publication_task
from relaysms_adapter_sdk.errors import (
    AuthenticationError,
    InvalidParamsError,
    RateLimitedError,
    TokenInvalidError,
    UpstreamError,
)

EVENTS = []


@contextmanager
def _fake_session():
    EVENTS.append("open")
    try:
        yield MagicMock()
    except Exception:
        EVENTS.append("rollback")
        raise
    EVENTS.append("commit")


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch):
    EVENTS.clear()
    monkeypatch.setattr(publication_task, "get_session", _fake_session)
    monkeypatch.setattr(publication_task, "record_publication", MagicMock())


def _stub_publications(monkeypatch, *, prepare_error=None, send_error=None):
    """Stub each publication step, making prepare or send raise the given error."""
    stub = MagicMock()
    stub.validate.return_value = (b"raw", b"seg", object())
    stub.prepare.return_value = MagicMock(platform="gmail")
    stub.prepare.side_effect = prepare_error

    def send(delivery):
        EVENTS.append("send")
        if send_error:
            raise send_error

    stub.send.side_effect = send
    for name in ("validate", "prepare", "send", "finish", "store_token"):
        monkeypatch.setattr(publication_task.publications, name, getattr(stub, name))
    return stub


def _run_with_publish_error(monkeypatch, error):
    stub = _stub_publications(monkeypatch, prepare_error=error)
    publication_task.publish_message("text", "sender", "https")
    return stub


@pytest.mark.parametrize(
    "error, reason",
    [
        (PayloadNotSupportedError("unsupported type"), "payload_not_supported"),
        (PayloadMalformedError("bad payload"), "payload_malformed"),
        (KeyNotFoundError("Token not found"), "token_not_found"),
        (KeyUnavailableError("key used"), "key_unavailable"),
        (TokenVerificationError("unknown key"), "token_verification_failed"),
    ],
)
def test_pipeline_errors_are_recorded_as_failed(monkeypatch, caplog, error, reason):
    _run_with_publish_error(monkeypatch, error)

    [record] = [r for r in caplog.records if "Failed to process payload" in r.message]
    assert record.levelno == logging.WARNING
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == reason


@pytest.mark.parametrize(
    "error, reason",
    [
        (ProtocolNotAllowedError("protocol not allowed"), "protocol_not_allowed"),
        (OfflineTagMissingError("missing tag"), "offline_tag_missing"),
        (OfflineTagInvalidError("invalid tag"), "offline_tag_invalid"),
    ],
)
def test_offline_refusals_are_rejected_not_failed(monkeypatch, caplog, error, reason):
    _run_with_publish_error(monkeypatch, error)

    assert "Rejected payload" in caplog.text
    kwargs = publication_task.record_publication.call_args.kwargs
    assert (kwargs["status"], kwargs["failure_reason"]) == ("rejected", reason)


def test_a_subclass_of_a_mapped_error_keeps_its_code(monkeypatch):
    class TruncatedPayloadError(PayloadMalformedError):
        pass

    _run_with_publish_error(monkeypatch, TruncatedPayloadError("short"))

    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["failure_reason"] == "payload_malformed"


@pytest.mark.parametrize(
    "code, reason, level",
    [
        (RateLimitedError.code, "adapter_rate_limited", logging.ERROR),
        (UpstreamError.code, "adapter_upstream", logging.ERROR),
        (-32099, "adapter_error", logging.ERROR),
        (InvalidParamsError.code, "adapter_invalid_params", logging.WARNING),
        (AuthenticationError.code, "adapter_auth_failed", logging.WARNING),
        (TokenInvalidError.code, "adapter_token_invalid", logging.WARNING),
    ],
)
def test_adapter_failures_record_a_code_and_log_by_reason(
    monkeypatch, caplog, code, reason, level
):
    error = AdapterIntegrationError("Google returned 400: to=a@b.c", code=code)
    _stub_publications(monkeypatch, send_error=error)

    publication_task.publish_message("text", "sender", "https")

    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["failure_reason"] == reason
    [record] = [r for r in caplog.records if "Failed to publish message" in r.message]
    assert record.levelno == level


def test_a_failed_send_keeps_the_refreshed_token(monkeypatch, caplog):
    error = AdapterIntegrationError("boom", code=UpstreamError.code, token={"t": 2})
    stub = _stub_publications(monkeypatch, send_error=error)

    publication_task.publish_message("text", "sender", "https")

    assert "Failed to publish message" in caplog.text
    assert stub.store_token.call_args.args[2] == {"t": 2}
    stub.finish.assert_not_called()
    publication_task.record_publication.assert_called_once()
    assert publication_task.record_publication.call_args.kwargs["status"] == "failed"


def test_unexpected_error_is_caught_logged_and_recorded(monkeypatch, caplog):
    _run_with_publish_error(monkeypatch, RuntimeError("boom"))

    assert "unexpected error" in caplog.text.lower()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == "unexpected_error"


def test_success_records_published_stat(monkeypatch):
    stub = _stub_publications(monkeypatch)

    publication_task.publish_message("text", "sender", "https", country_code="CM")

    assert stub.prepare.call_args.kwargs["sender_id"] == "sender"
    assert EVENTS == ["open", "commit", "send", "open", "commit"]
    stub.finish.assert_called_once()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "published"
    assert kwargs["platform_name"] == "gmail"
    assert kwargs["country_code"] == "CM"


def test_incomplete_segment_session_skips_recording(monkeypatch):
    stub = _stub_publications(monkeypatch)
    stub.prepare.return_value = None

    publication_task.publish_message("text", "sender", "smtp")

    stub.send.assert_not_called()
    publication_task.record_publication.assert_not_called()


def test_a_recording_failure_after_the_send_is_not_a_failed_publication(
    monkeypatch, caplog
):
    stub = _stub_publications(monkeypatch)
    stub.finish.side_effect = RuntimeError("db dropped")

    publication_task.publish_message("text", "sender", "https")

    assert EVENTS == ["open", "commit", "send", "open", "rollback"]
    assert "couldn't record the result" in caplog.text
    publication_task.record_publication.assert_not_called()


def test_a_failed_payload_rolls_back_before_sending(monkeypatch):
    _run_with_publish_error(monkeypatch, PayloadMalformedError("bad payload"))

    assert EVENTS == ["open", "rollback", "open", "commit"]


def test_tag_is_passed_to_prepare(monkeypatch):
    stub = _stub_publications(monkeypatch)

    publication_task.publish_message("text", "sender", "https", "s3cret-tag")

    assert stub.prepare.call_args.kwargs["tag"] == "s3cret-tag"


def _span(sampled):
    flags = otel_trace.TraceFlags(otel_trace.TraceFlags.SAMPLED if sampled else 0)
    context = otel_trace.SpanContext(0xAB, 0xCD, is_remote=True, trace_flags=flags)
    return otel_trace.use_span(otel_trace.NonRecordingSpan(context))


@pytest.mark.parametrize(
    "error", [None, PayloadMalformedError("bad")], ids=["published", "failed"]
)
def test_records_the_sampled_trace_id(monkeypatch, error):
    _stub_publications(monkeypatch, prepare_error=error)

    with _span(sampled=True):
        publication_task.publish_message("text", "sender", "https")

    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["trace_id"] == f"{0xAB:032x}"


@pytest.mark.parametrize(
    "span", [lambda: _span(sampled=False), nullcontext], ids=["unsampled", "no-span"]
)
def test_records_no_trace_id_without_a_sampled_trace(monkeypatch, span):
    _stub_publications(monkeypatch)

    with span():
        publication_task.publish_message("text", "sender", "https")

    assert publication_task.record_publication.call_args.kwargs["trace_id"] is None


@pytest.fixture
def fake_span(monkeypatch):
    span = MagicMock()
    span.get_span_context.return_value = otel_trace.INVALID_SPAN_CONTEXT
    monkeypatch.setattr(otel_trace, "get_current_span", lambda: span)
    return span


def _span_attributes(span):
    return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}


def test_a_failed_publication_marks_its_span_as_an_error(monkeypatch, fake_span):
    _run_with_publish_error(
        monkeypatch, PayloadMalformedError("bad", platform_name="gmail")
    )

    assert _span_attributes(fake_span) == {
        "publication.status": "failed",
        "publication.platform": "gmail",
        "publication.failure_reason": "payload_malformed",
    }
    fake_span.set_status.assert_called_once_with(
        otel_trace.StatusCode.ERROR, "payload_malformed"
    )


@pytest.mark.parametrize(
    "error, status", [(None, "published"), (ProtocolNotAllowedError("no"), "rejected")]
)
def test_published_and_rejected_spans_are_not_errors(
    monkeypatch, fake_span, error, status
):
    _stub_publications(monkeypatch, prepare_error=error)

    publication_task.publish_message("text", "sender", "https")

    assert _span_attributes(fake_span)["publication.status"] == status
    fake_span.set_status.assert_not_called()


def test_an_unexpected_error_is_recorded_on_the_span(monkeypatch, fake_span):
    error = RuntimeError("boom")
    _run_with_publish_error(monkeypatch, error)

    fake_span.record_exception.assert_called_once_with(error)


def test_a_payload_failure_logs_its_cause(monkeypatch, caplog):
    error = PayloadMalformedError("Payload is not valid base64.")
    error.__cause__ = ValueError("Incorrect padding")

    _run_with_publish_error(monkeypatch, error)

    [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert record.getMessage() == (
        "Failed to process payload: Payload is not valid base64. (Incorrect padding)"
    )
