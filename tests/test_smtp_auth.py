# SPDX-License-Identifier: GPL-3.0-only

import email

import pytest

import smtp_auth


def make_message(auth_results=None, from_addr="user@example.com"):
    """Build a minimal email.message.Message with optional
    Authentication-Results headers."""
    msg = email.message.Message()
    if from_addr is not None:
        msg["From"] = from_addr
    for value in auth_results or []:
        msg["Authentication-Results"] = value
    return msg


class TestIsSenderAllowed:
    def test_denies_when_allowlist_empty(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_ALLOWED_SENDERS", set())
        assert smtp_auth.is_sender_allowed("user@example.com") is False

    def test_exact_match_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_ALLOWED_SENDERS", {"user@example.com"})
        assert smtp_auth.is_sender_allowed("USER@Example.com") is True
        assert smtp_auth.is_sender_allowed("other@example.com") is False

    def test_domain_entry_matches_any_local_part(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_ALLOWED_SENDERS", {"example.com"})
        assert smtp_auth.is_sender_allowed("someone@example.com") is True
        assert smtp_auth.is_sender_allowed("someone@other.com") is False

    def test_domain_entry_with_at_prefix_is_normalized_on_load(self, monkeypatch):
        monkeypatch.setenv("SMTP_ALLOWED_SENDERS", "@example.com")
        assert smtp_auth._load_allowed_senders() == {"example.com"}

    def test_rejects_address_without_at(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_ALLOWED_SENDERS", {"example.com"})
        assert smtp_auth.is_sender_allowed("not-an-email") is False

    def test_rejects_empty_address(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_ALLOWED_SENDERS", {"example.com"})
        assert smtp_auth.is_sender_allowed("") is False


class TestEvaluateAuthentication:
    def test_skipped_when_authserv_id_unconfigured(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", None)
        passed, _ = smtp_auth.evaluate_authentication(make_message())
        assert passed is True

    def test_fails_when_header_missing(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        passed, _ = smtp_auth.evaluate_authentication(make_message())
        assert passed is False

    def test_ignores_header_with_untrusted_authserv_id(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        msg = make_message(
            auth_results=[
                "attacker-controlled.example; dkim=pass; spf=pass",
            ]
        )
        passed, _ = smtp_auth.evaluate_authentication(msg)
        assert passed is False

    def test_passes_with_trusted_passing_header(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        monkeypatch.setattr(smtp_auth, "SMTP_REQUIRE_DKIM", True)
        monkeypatch.setattr(smtp_auth, "SMTP_REQUIRE_SPF", True)
        msg = make_message(
            auth_results=[
                "mx.google.com; dkim=pass header.d=example.com header.s=sel; "
                "spf=pass smtp.mailfrom=user@example.com",
            ]
        )
        passed, _ = smtp_auth.evaluate_authentication(msg)
        assert passed is True

    def test_fails_when_dkim_verdict_not_pass(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        monkeypatch.setattr(smtp_auth, "SMTP_REQUIRE_DKIM", True)
        monkeypatch.setattr(smtp_auth, "SMTP_REQUIRE_SPF", False)
        msg = make_message(auth_results=["mx.google.com; dkim=fail; spf=pass"])
        passed, _ = smtp_auth.evaluate_authentication(msg)
        assert passed is False

    def test_fails_when_spf_verdict_not_pass(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        monkeypatch.setattr(smtp_auth, "SMTP_REQUIRE_DKIM", False)
        monkeypatch.setattr(smtp_auth, "SMTP_REQUIRE_SPF", True)
        msg = make_message(auth_results=["mx.google.com; dkim=pass; spf=fail"])
        passed, _ = smtp_auth.evaluate_authentication(msg)
        assert passed is False

    def test_handles_folded_header(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        raw = (
            "From: user@example.com\r\n"
            "Authentication-Results: mx.google.com;\r\n"
            "       dkim=pass header.d=example.com;\r\n"
            "       spf=pass smtp.mailfrom=user@example.com\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = email.message_from_string(raw)
        passed, _ = smtp_auth.evaluate_authentication(msg)
        assert passed is True


class _FakeDKIM:
    def __init__(self, _raw, *, verified, domain):
        self._verified = verified
        self.domain = domain

    def verify(self):
        return self._verified


class TestVerifyDkimIndependently:
    def test_passes_when_signature_valid_and_aligned(self, monkeypatch):
        monkeypatch.setattr(
            smtp_auth.dkim,
            "DKIM",
            lambda raw: _FakeDKIM(raw, verified=True, domain=b"example.com"),
        )
        passed, _ = smtp_auth.verify_dkim_independently(b"raw", "user@example.com")
        assert passed is True

    def test_fails_when_signature_invalid(self, monkeypatch):
        monkeypatch.setattr(
            smtp_auth.dkim,
            "DKIM",
            lambda raw: _FakeDKIM(raw, verified=False, domain=b"example.com"),
        )
        passed, _ = smtp_auth.verify_dkim_independently(b"raw", "user@example.com")
        assert passed is False

    def test_fails_when_domain_misaligned(self, monkeypatch):
        monkeypatch.setattr(
            smtp_auth.dkim,
            "DKIM",
            lambda raw: _FakeDKIM(raw, verified=True, domain=b"evil.example"),
        )
        passed, _ = smtp_auth.verify_dkim_independently(b"raw", "user@example.com")
        assert passed is False

    def test_handles_verification_errors_gracefully(self, monkeypatch):
        def _raise(_raw):
            raise ValueError("boom")

        monkeypatch.setattr(smtp_auth.dkim, "DKIM", _raise)
        passed, _ = smtp_auth.verify_dkim_independently(b"raw", "user@example.com")
        assert passed is False


class TestEvaluate:
    def test_independent_dkim_only_runs_when_enabled(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", None)
        monkeypatch.setattr(smtp_auth, "SMTP_VERIFY_DKIM_INDEPENDENTLY", False)
        monkeypatch.setattr(
            smtp_auth.dkim,
            "DKIM",
            lambda raw: _FakeDKIM(raw, verified=False, domain=b"example.com"),
        )
        passed, _ = smtp_auth.evaluate(make_message(), b"raw", "user@example.com")
        assert passed is True

    def test_independent_dkim_runs_and_can_fail_when_enabled(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", None)
        monkeypatch.setattr(smtp_auth, "SMTP_VERIFY_DKIM_INDEPENDENTLY", True)
        monkeypatch.setattr(
            smtp_auth.dkim,
            "DKIM",
            lambda raw: _FakeDKIM(raw, verified=False, domain=b"example.com"),
        )
        passed, _ = smtp_auth.evaluate(make_message(), b"raw", "user@example.com")
        assert passed is False

    def test_independent_dkim_skipped_when_primary_already_failed(self, monkeypatch):
        monkeypatch.setattr(smtp_auth, "SMTP_TRUSTED_AUTHSERV_ID", "mx.google.com")
        monkeypatch.setattr(smtp_auth, "SMTP_VERIFY_DKIM_INDEPENDENTLY", True)

        def _fail_if_called(_raw):
            pytest.fail(
                "independent DKIM check should not run when primary check failed"
            )

        monkeypatch.setattr(smtp_auth.dkim, "DKIM", _fail_if_called)
        passed, _ = smtp_auth.evaluate(make_message(), b"raw", "user@example.com")
        assert passed is False
