# SPDX-License-Identifier: GPL-3.0-only
"""relaysms-adapter: link an account and send with the adapter in a repository.

Each call runs the adapter in its own process, as the Publisher does. The
linked account, config and state live in .relaysms/ next to adapter.toml.
"""

import argparse
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import time
import uuid
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from rich.console import Console
    from rich.json import JSON
    from rich.prompt import Prompt
    from rich.text import Text
except ImportError:
    sys.exit("The console needs rich: pip install 'relaysms-adapter-sdk[console]'")

from relaysms_adapter_sdk import log, manifest, wire
from relaysms_adapter_sdk.errors import AdapterError
from relaysms_adapter_sdk.manifest import Category, Manifest, ManifestError, Protocol
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV
from relaysms_adapter_sdk.types import (
    Account,
    Attachment,
    AuthorizationRequest,
    CodeExchangeRequest,
    CodeRequest,
    CodeVerificationRequest,
    Message,
    PasswordVerificationRequest,
    RevokeRequest,
    SendRequest,
)

WORKDIR = ".relaysms"
REDIRECT_TIMEOUT = 300
LEVEL_STYLES = {"DEBUG": "dim", "INFO": "cyan", "WARNING": "yellow"}

console = Console()


class ConsoleError(Exception):
    pass


@dataclass(frozen=True)
class Workspace:
    root: Path
    manifest: Manifest

    @property
    def config_dir(self) -> Path:
        return self.root / WORKDIR / "config"

    @property
    def state_dir(self) -> Path:
        return self.root / WORKDIR / "state"

    @property
    def account_file(self) -> Path:
        return self.root / WORKDIR / "account.json"


def call(ws: Workspace, method: str, params: Any) -> Any:
    """Run one method in a new adapter process and return its result."""
    ws.config_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        CONFIG_DIR_ENV: str(ws.config_dir),
        STATE_DIR_ENV: str(ws.state_dir),
    }
    process = subprocess.run(
        [sys.executable, "-m", "relaysms_adapter_sdk", ws.manifest.entry],
        input=wire.encode_request(method, params) + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=ws.root,
        check=False,
    )
    for line in process.stderr.splitlines():
        _show_log(line)
    if process.returncode != 0 or not process.stdout.strip():
        raise ConsoleError(f"The adapter exited with code {process.returncode}.")
    return wire.parse_response(process.stdout)


def link(ws: Workspace, args: argparse.Namespace) -> None:
    if ws.manifest.protocol is Protocol.OAUTH2:
        account = _link_oauth2(ws, args)
    else:
        account = _link_pnba(ws, args)
    _save_account(ws, account)
    console.print(Text(f"Linked {account['identifier']}.", style="green"))


def send(ws: Workspace, args: argparse.Namespace) -> None:
    account = None if args.offline else _load_account(ws)
    category = ws.manifest.category
    recipient = args.to
    if recipient is None and category in {Category.EMAIL, Category.MESSAGE}:
        recipient = Prompt.ask("To")
    subject = args.subject
    if subject is None and category is Category.EMAIL:
        subject = Prompt.ask("Subject", default="")
    body = args.body if args.body is not None else Prompt.ask("Message")

    request = SendRequest(
        message=Message(
            body=body,
            recipient=recipient,
            subject=subject,
            attachments=tuple(_attachment(Path(path)) for path in args.attach),
        ),
        account=None if account is None else wire.from_json(Account, account),
    )
    try:
        result = call(ws, "send_message", request)
    except AdapterError as e:
        if account is not None and e.token:
            _save_account(ws, {**account, "token": e.token})
        raise
    if account is not None and result.get("token"):
        _save_account(ws, {**account, "token": result["token"]})
    console.print(Text("Sent.", style="green"))


def revoke(ws: Workspace, _args: argparse.Namespace) -> None:
    account = _load_account(ws)
    call(ws, "revoke", RevokeRequest(wire.from_json(Account, account)))
    ws.account_file.unlink()
    console.print(Text(f"Unlinked {account['identifier']}.", style="green"))


def call_method(ws: Workspace, args: argparse.Namespace) -> None:
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        raise ConsoleError(f"params isn't valid JSON: {e.msg}") from e
    console.print(JSON.from_data(call(ws, args.method, params)), soft_wrap=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="relaysms-adapter",
        description="Link an account and send messages with an adapter.",
    )
    parser.add_argument(
        "--dir", type=Path, default=Path(), help="adapter repository (default: .)"
    )
    commands = parser.add_subparsers(required=True, metavar="command")

    link_parser = commands.add_parser("link", help="link an account")
    link_parser.add_argument("--phone", help="PNBA: phone number")
    link_parser.add_argument("--channel", help="PNBA: channel to send the code by")
    link_parser.add_argument("--redirect-url", help="OAuth2: redirect URL to use")
    link_parser.add_argument(
        "--no-browser", action="store_true", help="OAuth2: only print the URL"
    )
    link_parser.set_defaults(handler=link)

    send_parser = commands.add_parser("send", help="send a message")
    send_parser.add_argument("--to")
    send_parser.add_argument("--subject")
    send_parser.add_argument("--body")
    send_parser.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="repeatable"
    )
    send_parser.add_argument(
        "--offline", action="store_true", help="send without a linked account"
    )
    send_parser.set_defaults(handler=send)

    revoke_parser = commands.add_parser("revoke", help="unlink the account")
    revoke_parser.set_defaults(handler=revoke)

    call_parser = commands.add_parser("call", help="call any method")
    call_parser.add_argument("method")
    call_parser.add_argument("params", nargs="?", default="{}", help="JSON object")
    call_parser.set_defaults(handler=call_method)

    args = parser.parse_args(argv)
    try:
        root = args.dir.resolve()
        args.handler(Workspace(root, manifest.load(root)), args)
    except (ConsoleError, AdapterError, ManifestError) as e:
        console.print(Text(f"Error: {e}", style="bold red"))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


def _link_oauth2(ws: Workspace, args: argparse.Namespace) -> dict[str, Any]:
    request_identifier = uuid.uuid4().hex
    auth = call(
        ws,
        "create_authorization_url",
        AuthorizationRequest(
            code_verifier=secrets.token_urlsafe(48),
            redirect_url=args.redirect_url,
            request_identifier=request_identifier,
        ),
    )
    redirect_url = args.redirect_url or auth.get("redirect_url")
    console.print("Authorize the account at:")
    console.print(Text(auth["url"], style="link " + auth["url"]), soft_wrap=True)
    if not args.no_browser:
        webbrowser.open(auth["url"])

    params = _wait_for_redirect(redirect_url) if redirect_url else None
    if params is None:
        pasted = Prompt.ask("Paste the URL you were redirected to")
        params = _query(pasted)
    if "error" in params:
        raise ConsoleError(f"Authorization failed: {params['error']}")
    if "code" not in params:
        raise ConsoleError("The redirect has no code.")
    if auth.get("state") and params.get("state") != auth["state"]:
        raise ConsoleError("The redirect's state doesn't match.")

    return call(
        ws,
        "exchange_code",
        CodeExchangeRequest(
            code=params["code"],
            code_verifier=auth.get("code_verifier"),
            redirect_url=redirect_url,
            request_identifier=request_identifier,
        ),
    )


def _link_pnba(ws: Workspace, args: argparse.Namespace) -> dict[str, Any]:
    phone_number = args.phone or Prompt.ask("Phone number")
    request_identifier = uuid.uuid4().hex
    sent = call(
        ws, "send_code", CodeRequest(phone_number, args.channel, request_identifier)
    )
    console.print(sent.get("message") or "Code sent.")
    if sent.get("expires_at"):
        console.print(Text(f"It expires at {sent['expires_at']}.", style="dim"))

    code = Prompt.ask("Code")
    result = call(
        ws,
        "verify_code",
        CodeVerificationRequest(phone_number, code, args.channel, request_identifier),
    )
    if result.get("password_required"):
        password = Prompt.ask("Two-step verification password", password=True)
        result = call(
            ws,
            "verify_password",
            PasswordVerificationRequest(phone_number, password, request_identifier),
        )
    return result


def _wait_for_redirect(url: str) -> dict[str, str] | None:
    """Catch the redirect on a local server; None when the URL isn't local."""
    target = urlparse(url)
    if target.scheme != "http" or target.hostname not in {"localhost", "127.0.0.1"}:
        return None

    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != (target.path or "/"):
                self.send_error(404)
                return
            received.update(_query(self.path))
            body = b"Done. You can close this tab and go back to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    try:
        server = HTTPServer((target.hostname, target.port or 80), Handler)
    except OSError as e:
        console.print(Text(f"Can't listen on {url}: {e.strerror}", style="yellow"))
        return None

    waiting = f"Waiting for the redirect to {url} (Ctrl-C to paste it)"
    console.print(Text(waiting, style="dim"))
    deadline = time.monotonic() + REDIRECT_TIMEOUT
    server.timeout = 1
    try:
        with server:
            while not received and time.monotonic() < deadline:
                server.handle_request()
    except KeyboardInterrupt:
        console.print()
        return None
    return received or None


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def _attachment(path: Path) -> Attachment:
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ConsoleError(f"Can't read {path}: {e.strerror}") from e
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Attachment(data=data, filename=path.name, mimetype=mimetype)


def _load_account(ws: Workspace) -> dict[str, Any]:
    try:
        return json.loads(ws.account_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConsoleError("No linked account; run relaysms-adapter link.") from None


def _save_account(ws: Workspace, account: dict[str, Any]) -> None:
    ws.account_file.parent.mkdir(parents=True, exist_ok=True)
    ws.account_file.write_text(json.dumps(account, indent=2), encoding="utf-8")
    ws.account_file.chmod(0o600)


def _show_log(line: str) -> None:
    entry = log.parse(line)
    if entry is None:
        console.print(Text(line, style="dim"))
        return
    level, logger, message = entry["level"], entry["logger"], entry["message"]
    style = LEVEL_STYLES.get(level, "bold red")
    console.print(Text.assemble((f"{level:<8}", style), (f"{logger} ", "dim"), message))
    if entry.get("traceback"):
        console.print(Text(entry["traceback"], style="red"))


if __name__ == "__main__":
    sys.exit(main())
