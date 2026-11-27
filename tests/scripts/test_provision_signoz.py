# SPDX-License-Identifier: GPL-3.0-only

import copy
import importlib.util
import io
import textwrap
import urllib.error
from email.message import Message

import pytest

from tests.scripts import REPO

spec = importlib.util.spec_from_file_location(
    "provision_signoz", REPO / "scripts" / "provision_signoz.py"
)
provision_signoz = importlib.util.module_from_spec(spec)  # pyright: ignore[reportArgumentType]
spec.loader.exec_module(provision_signoz)  # pyright: ignore[reportOptionalMemberAccess]

WEBHOOK_URL = "https://chat.example.com/hooks/abc"
ALERT_EMAIL = "ops@example.com"
GUIDE = (REPO / "docs/operating/observability.md").read_text(encoding="utf-8")
RULES = provision_signoz.read("alerts.json")
CHANNEL = provision_signoz.read("channel.json")


class FakeSigNoz:
    def __init__(self, channels=(), rules=(), dashboard_status=None):
        self.replies = {
            "/api/v1/channels": [{"name": name} for name in channels],
            "/api/v3/rules?limit=1000": {"rules": [{"alert": name} for name in rules]},
        }
        self.dashboard_status = dashboard_status
        self.posted = []

    def call(self, method, path, body=None):
        if method == "GET":
            return self.replies[path]
        if path == "/api/v2/dashboards" and self.dashboard_status:
            raise urllib.error.HTTPError(
                path, self.dashboard_status, "refused", Message(), None
            )
        self.posted.append((path, body))
        return {}


def test_everything_is_created_in_an_empty_signoz():
    signoz = FakeSigNoz()

    provision_signoz.provision(signoz, WEBHOOK_URL, ALERT_EMAIL)

    dashboard, webhook, email, *rules = signoz.posted
    assert dashboard[0] == "/api/v2/dashboards"
    assert webhook[0] == email[0] == "/api/v1/channels"
    assert webhook[1]["slack_configs"][0]["api_url"] == WEBHOOK_URL
    assert email[1]["email_configs"][0]["to"] == ALERT_EMAIL
    expected = copy.deepcopy(RULES)
    for rule in expected:
        rule["condition"]["thresholds"]["spec"][0]["channels"] = [
            CHANNEL["name"],
            email[1]["name"],
        ]
    assert rules == [("/api/v2/rules", rule) for rule in expected]


@pytest.mark.parametrize(
    ("webhook_url", "alert_email", "config"),
    [(WEBHOOK_URL, "", "slack_configs"), ("", ALERT_EMAIL, "email_configs")],
)
def test_rules_send_only_to_the_channel_given(webhook_url, alert_email, config):
    signoz = FakeSigNoz()

    provision_signoz.provision(signoz, webhook_url, alert_email)

    _, (_, channel), *rules = signoz.posted
    assert config in channel
    for _, body in rules:
        [threshold] = body["condition"]["thresholds"]["spec"]
        assert threshold["channels"] == [channel["name"]]


def test_what_exists_is_skipped():
    first, *others = [rule["alert"] for rule in RULES]
    signoz = FakeSigNoz(channels=[CHANNEL["name"]], rules=[first], dashboard_status=409)

    provision_signoz.provision(signoz, WEBHOOK_URL, "")

    assert [body["alert"] for _, body in signoz.posted] == others
    for _, body in signoz.posted:
        [threshold] = body["condition"]["thresholds"]["spec"]
        assert threshold["channels"] == [CHANNEL["name"]]


def test_a_refused_dashboard_stops_the_run():
    signoz = FakeSigNoz(dashboard_status=400)

    with pytest.raises(urllib.error.HTTPError):
        provision_signoz.provision(signoz, WEBHOOK_URL, "")
    assert signoz.posted == []


def test_main_passes_on_the_webhook_and_email(monkeypatch):
    for name, value in {
        "SIGNOZ_URL": "http://127.0.0.1:8090",
        "SIGNOZ_EMAIL": "admin@example.com",
        "SIGNOZ_PASSWORD": "password",
        "SIGNOZ_WEBHOOK_URL": "",
        "SIGNOZ_ALERT_EMAIL": ALERT_EMAIL,
    }.items():
        monkeypatch.setenv(name, value)
    calls = []
    monkeypatch.setattr(provision_signoz, "SigNoz", lambda *args: "signoz")
    monkeypatch.setattr(provision_signoz, "provision", lambda *args: calls.append(args))

    provision_signoz.main()

    assert calls == [("signoz", "", ALERT_EMAIL)]


def test_a_failed_login_shows_no_secrets(monkeypatch):
    env = {
        "SIGNOZ_URL": "http://127.0.0.1:8090",
        "SIGNOZ_EMAIL": "admin@example.com",
        "SIGNOZ_PASSWORD": "hunter2-password",
        "SIGNOZ_WEBHOOK_URL": WEBHOOK_URL,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    def refuse(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "refused", Message(), io.BytesIO(b"denied")
        )

    monkeypatch.setattr(provision_signoz.OPENER, "open", refuse)

    with pytest.raises(SystemExit) as error:
        provision_signoz.main()
    message = str(error.value)
    assert "401 denied" in message
    assert not any(env[name] in message for name in list(env)[1:])


@pytest.mark.parametrize("rule", RULES, ids=[rule["alert"] for rule in RULES])
def test_the_guide_matches_the_rule(rule):
    [query] = rule["condition"]["compositeQuery"]["queries"]
    [threshold] = rule["condition"]["thresholds"]["spec"]

    section = GUIDE.split(f"#### {rule['alert']}\n")[1].partition("\n#")[0]
    assert query["spec"]["filter"]["expression"] in section
    assert rule["annotations"]["description"] in section

    group_by = [field["name"] for field in query["spec"]["groupBy"]]
    assert rule["notificationSettings"]["groupBy"] == group_by
    assert threshold["op"] == "above"

    [aggregation] = query["spec"]["aggregations"]
    match = threshold["matchType"].replace("_", " ").upper()
    minutes = rule["evaluation"]["spec"]["evalWindow"].removesuffix("m0s")
    unit = {"": "", "s": " seconds"}[threshold["targetUnit"]]
    [row] = [line for line in GUIDE.splitlines() if f"| [{rule['alert']}](" in line]
    assert row.endswith(
        f"| `{aggregation['expression']}`"
        f" | {', '.join(f'`{name}`' for name in group_by)}"
        f" | {match}, {minutes} minutes"
        f" | {threshold['name']}, {threshold['target']}{unit} |"
    )


@pytest.mark.parametrize("field", ["title", "text"])
def test_the_guide_matches_the_channel_template(field):
    template = CHANNEL["slack_configs"][0][field]
    assert textwrap.indent(template, "   ") in GUIDE


def test_the_dashboard_counts_refused_requests_like_the_rule():
    [rule] = [rule for rule in RULES if rule["alert"] == "Refused requests"]
    [query] = rule["condition"]["compositeQuery"]["queries"]
    panel = provision_signoz.read("dashboard.json")["spec"]["panels"]["refused"]
    [panel_query] = panel["spec"]["queries"]

    assert panel_query["spec"]["plugin"]["spec"]["filter"] == query["spec"]["filter"]
