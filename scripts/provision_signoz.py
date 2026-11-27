# SPDX-License-Identifier: GPL-3.0-only
"""Create the dashboard, notification channels and alert rules that SigNoz lacks.

Run by setup-observability.sh, which sets SIGNOZ_URL, SIGNOZ_EMAIL, SIGNOZ_PASSWORD,
SIGNOZ_WEBHOOK_URL and SIGNOZ_ALERT_EMAIL. One of the last two may be blank.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RESOURCES = Path(__file__).resolve().parent.parent / "observability" / "signoz"
# Bypasses any proxy set in the environment.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read(name: str) -> Any:
    return json.loads((RESOURCES / name).read_text(encoding="utf-8"))


class SigNoz:
    def __init__(self, url: str, email: str, password: str):
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        query = urllib.parse.urlencode({"email": email, "ref": url})
        context = self.call("GET", f"/api/v2/sessions/context?{query}")
        credentials = {
            "email": email,
            "password": password,
            "orgId": context["orgs"][0]["id"],
        }
        session = self.call("POST", "/api/v2/sessions/email_password", credentials)
        self.headers["Authorization"] = f"Bearer {session['accessToken']}"

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + path, data, self.headers, method=method
        )
        with OPENER.open(request, timeout=30) as response:
            return json.load(response)["data"]


def provision(signoz: SigNoz, webhook_url: str, alert_email: str) -> None:
    dashboard = read("dashboard.json")
    try:
        signoz.call("POST", "/api/v2/dashboards", dashboard)
        print("Created the dashboard")
    except urllib.error.HTTPError as e:
        if e.code != 409:
            raise
        print("The dashboard already exists, skipping")

    channels = []
    if webhook_url:
        channel = read("channel.json")
        channel["slack_configs"][0]["api_url"] = webhook_url
        channels.append(channel)
    if alert_email:
        channels.append(
            {
                "name": "Publisher email",
                "email_configs": [
                    {
                        "send_resolved": True,
                        "to": alert_email,
                        "html": '{{ template "email.default.html" . }}',
                    }
                ],
            }
        )
    names = [channel["name"] for channel in channels]
    existing_channels = {c["name"] for c in signoz.call("GET", "/api/v1/channels")}
    for channel in channels:
        if channel["name"] in existing_channels:
            print(f"Channel {channel['name']!r} already exists, skipping")
        else:
            signoz.call("POST", "/api/v1/channels", channel)
            print(f"Created channel {channel['name']!r}")

    existing = {
        rule["alert"]
        for rule in signoz.call("GET", "/api/v3/rules?limit=1000")["rules"]
    }
    for rule in read("alerts.json"):
        if rule["alert"] in existing:
            print(f"Rule {rule['alert']!r} already exists, skipping")
            continue
        rule["condition"]["thresholds"]["spec"][0]["channels"] = names
        signoz.call("POST", "/api/v2/rules", rule)
        print(f"Created rule {rule['alert']!r}")


def main() -> None:
    env = os.environ
    try:
        signoz = SigNoz(env["SIGNOZ_URL"], env["SIGNOZ_EMAIL"], env["SIGNOZ_PASSWORD"])
        provision(signoz, env["SIGNOZ_WEBHOOK_URL"], env["SIGNOZ_ALERT_EMAIL"])
    except urllib.error.HTTPError as e:
        path = urllib.parse.urlsplit(e.url).path
        sys.exit(f"SigNoz refused {path}: {e.code} {e.read().decode(errors='replace')}")
    except (OSError, ValueError) as e:
        sys.exit(f"Couldn't use the SigNoz API: {e}")


if __name__ == "__main__":
    main()
