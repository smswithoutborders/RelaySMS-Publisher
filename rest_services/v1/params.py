# SPDX-License-Identifier: GPL-3.0-only

from fastapi import Query

NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"


def filter_query(max_length: int, description: str):
    return Query(
        None,
        max_length=max_length,
        pattern=NAME_PATTERN,
        description=description,
    )
