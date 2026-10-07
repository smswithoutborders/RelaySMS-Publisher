# SPDX-License-Identifier: GPL-3.0-only
"""Writes a results table to the GitHub Actions job summary.

pyproject.toml loads it into every pytest run; it does nothing outside GitHub
Actions. It only imports pytest, since the e2e job installs nothing else.

Rows group by test directory, or by what a test module names in SUMMARY_BY:
"test" for the test function, or a parametrized fixture such as "dialect".
"""

import os
from collections import Counter

import pytest

OUTCOMES = ("passed", "failed", "skipped")
MAX_MESSAGE_LENGTH = 200


def pytest_configure(config: pytest.Config) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        config.pluginmanager.register(Summary(path), "github-summary")


def _group(item: pytest.Item) -> str:
    by = getattr(getattr(item, "module", None), "SUMMARY_BY", "dir")
    if by == "test":
        return getattr(item, "originalname", item.name)
    callspec = getattr(item, "callspec", None)
    if callspec and by in callspec.params:
        return str(callspec.params[by])
    parts = item.path.relative_to(item.config.rootpath).parent.parts[1:]
    return "/".join(parts) or "top level"


class Summary:
    def __init__(self, path: str):
        self.path = path
        self.outcomes: dict[str, str] = {}
        self.failures: dict[str, str] = {}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # A failure in setup, call or teardown fails the test.
        if report.failed:
            self.outcomes[report.nodeid] = "failed"
            crash = getattr(report.longrepr, "reprcrash", None)
            message = crash.message if crash else str(report.longrepr)
            self.failures[report.nodeid] = message.splitlines()[0][:MAX_MESSAGE_LENGTH]
        elif report.skipped:
            self.outcomes.setdefault(report.nodeid, "skipped")
        elif report.when == "call":
            self.outcomes.setdefault(report.nodeid, "passed")

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        counts: dict[str, Counter[str]] = {}
        for item in session.items:
            if outcome := self.outcomes.get(item.nodeid):
                counts.setdefault(_group(item), Counter())[outcome] += 1
        total = Counter(self.outcomes.values())
        totals = ", ".join(f"{total[o]} {o}" for o in OUTCOMES if total[o])

        lines = [
            f"### {'❌' if self.failures else '✅'} {totals or 'No tests ran'}",
            "",
            "| Group | Passed | Failed | Skipped |",
            "| --- | ---: | ---: | ---: |",
            *(
                f"| {group} | " + " | ".join(str(c[o] or "") for o in OUTCOMES) + " |"
                for group, c in counts.items()
            ),
        ]
        if self.failures:
            lines += ["", "**Failures**", ""]
            lines += [f"- `{nodeid}`: {msg}" for nodeid, msg in self.failures.items()]

        with open(self.path, "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n\n")
