# Echo Adapter

An example PNBA adapter for the [RelaySMS Adapter SDK](../../README.md). It accepts one fixed code and appends each message to `outbox.jsonl` in its state directory.

```bash
python3 -m venv venv
venv/bin/pip install -e ../.. -e '.[dev]'
mkdir -p .relaysms/config && echo '{"code": "123456"}' > .relaysms/config/credentials.json
venv/bin/pytest
venv/bin/relaysms-adapter link --phone +237600000000
venv/bin/relaysms-adapter send --to friend --body hello
```
