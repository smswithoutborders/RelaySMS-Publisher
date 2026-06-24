# SPDX-License-Identifier: GPL-3.0-only

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from logutils import get_logger

logger = get_logger(__name__)


class AdapterIPCHandler:
    """Handles secure inter-process communication with adapter scripts via JSON pipes."""

    @staticmethod
    def invoke(
        adapter_path: str, venv_path: str, method: str, params: Optional[dict] = None
    ) -> Dict[str, Any]:
        """Invokes an adapter method securely using JSON payload piping over standard IO."""
        a_base = Path(adapter_path).resolve()
        v_base = Path(venv_path).resolve()

        exec_name = "bin/python3"
        python_exec = v_base / exec_name
        adapter_main = a_base / "main.py"

        if not python_exec.is_file():
            raise FileNotFoundError(f"[!] Python executable missing at: {python_exec}")
        if not adapter_main.is_file():
            raise FileNotFoundError(
                f"[!] Adapter script entry point missing at: {adapter_main}"
            )

        command = [str(python_exec), str(adapter_main)]
        payload = json.dumps({"method": method, "params": params or {}})

        logger.info(
            "[+] Starting subprocess for method '%s' on %s", method, a_base.name
        )
        process = None

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            stdout, stderr = process.communicate(input=payload, timeout=60)

            if stderr.strip():
                for line in stderr.strip().splitlines():
                    if line.strip():
                        logger.debug("[--> SUBPROCESS] %s", line.strip())

            if process.returncode != 0:
                logger.error("[!] Subprocess failed with code %s", process.returncode)
                raise RuntimeError(stderr.strip())

            clean_stdout = stdout.strip()
            if not clean_stdout:
                logger.error("[!] Empty output response from adapter.")
                return {"result": None, "error": "Empty response from adapter."}

            try:
                response = json.loads(clean_stdout)
            except json.JSONDecodeError:
                logger.error("[!] Malformed JSON response received: %s", clean_stdout)
                return {"result": None, "error": "Invalid JSON response payload."}

            logger.info("[+] Completed method '%s' execution successfully", method)
            return {"result": response.get("result"), "error": response.get("error")}

        except subprocess.TimeoutExpired as exc:
            if process:
                process.kill()
                process.communicate()
            logger.error("[!] Subprocess execution timed out.")
            raise RuntimeError("Adapter invocation timed out.") from exc

        except Exception as e:
            if process:
                try:
                    process.kill()
                except OSError:
                    pass
            logger.error("[!] Unexpected failure during IPC invocation loop: %s", e)
            raise
