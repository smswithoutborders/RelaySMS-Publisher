# SPDX-License-Identifier: GPL-3.0-only
"""Keyset pagination over a timestamp and an id, newest first."""

import base64
import binascii
import datetime
import json
import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from publisher.db.types import as_utc

Direction = Literal["next", "prev"]


class InvalidCursorError(ValueError):
    pass


@dataclass(frozen=True)
class Cursor:
    time: datetime.datetime
    id: int
    direction: Direction


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None
    prev_cursor: str | None


def encode_cursor(time: datetime.datetime, row_id: int, direction: Direction) -> str:
    payload = json.dumps(
        {"t": as_utc(time).isoformat(), "i": row_id, "d": direction},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Cursor:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        time = as_utc(datetime.datetime.fromisoformat(data["t"]))
        row_id = data["i"]
        direction = data["d"]
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise InvalidCursorError("Invalid cursor.") from None

    if type(row_id) is not int or row_id < 1 or direction not in ("next", "prev"):
        raise InvalidCursorError("Invalid cursor.")
    return Cursor(time=time, id=row_id, direction=direction)


def paginate[T](
    stmt: Select,
    time_column: InstrumentedAttribute,
    id_column: InstrumentedAttribute,
    *,
    limit: int,
    cursor: Cursor | None,
    fetch: Callable[[Select], Sequence[T]],
) -> Page[T]:
    """Run stmt for the page after cursor. Rows need the two columns as attributes."""
    backward = cursor is not None and cursor.direction == "prev"
    if cursor is not None:
        # OR form: row-value comparisons aren't consistent across databases.
        beyond = operator.gt if backward else operator.lt
        stmt = stmt.where(
            or_(
                beyond(time_column, cursor.time),
                and_(time_column == cursor.time, beyond(id_column, cursor.id)),
            )
        )
    order = (
        (time_column.asc(), id_column.asc())
        if backward
        else (time_column.desc(), id_column.desc())
    )
    # One extra row tells whether there is more beyond this page.
    rows = fetch(stmt.order_by(*order).limit(limit + 1))
    has_more = len(rows) > limit
    items = list(rows[:limit])
    if backward:
        items.reverse()

    if not items:
        return Page(items=[], next_cursor=None, prev_cursor=None)

    if backward:
        has_next, has_prev = True, has_more
    else:
        has_next, has_prev = has_more, cursor is not None

    def encode(item: T, direction: Direction) -> str:
        return encode_cursor(
            getattr(item, time_column.key), getattr(item, id_column.key), direction
        )

    return Page(
        items=items,
        next_cursor=encode(items[-1], "next") if has_next else None,
        prev_cursor=encode(items[0], "prev") if has_prev else None,
    )
