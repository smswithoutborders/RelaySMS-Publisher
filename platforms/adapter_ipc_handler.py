"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import os
import json
import subprocess


class AdapterIPCHandler:
    """
    Handles inter-process communication (IPC) with an adapter script using JSON over pipes.
    """

    @staticmethod
    def invoke(adapter_path, venv_path, method, params=None):
        """
        Invokes the adapter using JSON over pipes and subprocess IPC.

        Args:
            adapter_path (str): Path to the adapter script.
            venv_path (str): Path to the virtual environment containing the Python executable.
            method (str): The method to invoke on the adapter.
            params (dict): Parameters to pass to the adapter method.
                Defaults to an empty dictionary if None.

        Returns:
            dict: A dictionary containing 'result' and 'error' keys.

        Raises:
            FileNotFoundError: If the Python executable is not found.
            RuntimeError: For subprocess failures or invalid adapter responses.
        """
        python_exec = os.path.join(venv_path, "bin", "python3")
        adapter_main_path = os.path.join(adapter_path, "main.py")
        if not os.path.isfile(python_exec):
            raise FileNotFoundError(f"Python executable not found at: {python_exec}")

        command = [python_exec, adapter_main_path]
        payload = json.dumps({"method": method, "params": params or {}})

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            stdout, stderr = process.communicate(input=payload, timeout=15)

            if process.returncode != 0:
                raise RuntimeError(
                    f"Adapter subprocess exited with error:\n{stderr.strip()}"
                )

            if not stdout.strip():
                return {"result": None, "error": "Empty response from adapter."}

            try:
                response = json.loads(stdout.strip())
            except json.JSONDecodeError:
                return {
                    "result": None,
                    "error": f"Invalid JSON from adapter: {stdout.strip()}",
                }

            return {"result": response.get("result"), "error": response.get("error")}

        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise RuntimeError("Adapter invocation timed out.") from exc
        except Exception as e:
            raise RuntimeError(f"Failed to invoke adapter: {e}") from e
