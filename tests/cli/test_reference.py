# SPDX-License-Identifier: GPL-3.0-only

import re

import click

from publisher import config
from publisher.cli import cli


def reference_section(heading: str) -> str:
    text = (config.ROOT / "docs" / "reference" / "cli.md").read_text()
    return text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def commands(group: click.Group, prefix: str = "") -> set[str]:
    names = set()
    for name, command in group.commands.items():
        if isinstance(command, click.Group):
            names |= commands(command, f"{prefix}{name} ")
        else:
            names.add(f"{prefix}{name}")
    return names


def test_cli_reference_lists_every_publisher_command():
    section = reference_section("publisher.sh")
    documented = set()
    for group, cells in re.findall(r"^\| `([a-z-]+)` \| ([^|]+) \|", section, re.M):
        documented |= {f"{group} {name}" for name in re.findall(r"`([a-z -]+)`", cells)}

    assert commands(cli) - documented == set(), "missing from docs/reference/cli.md"
    assert documented - commands(cli) == set(), "in docs/reference/cli.md, not the CLI"


def test_cli_reference_lists_every_manage_command():
    usage = re.search(
        r"Usage: \$0 \{([^}]+)\}", (config.ROOT / "manage.sh").read_text()
    )
    assert usage
    actual = set(usage[1].split("|"))
    documented = set(re.findall(r"`([a-z]+)`", reference_section("manage.sh")))

    assert actual - documented == set(), "missing from docs/reference/cli.md"
    assert documented - actual == set(), "in docs/reference/cli.md, not manage.sh"
