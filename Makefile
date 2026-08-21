# SPDX-License-Identifier: GPL-3.0-only

python        := python3
grpc_host     := $${HOST:-127.0.0.1}
grpc_port     := $${GRPC_PORT:-6000}
fastapi_port  := $${PORT:-16000}

define log
	@echo "[$(shell date +'%Y-%m-%d %H:%M:%S')] [$1] $2"
endef

.PHONY: \
	grpc-compile \
	grpc-server-start \
	fastapi-server-start \
	celery-worker-start \
	smtp-listener-start \
	run \
	payload-specs-fetch \
	payload-specs-build \
	payload-specs-compile \
	build-setup \
	migrate-up

grpc-compile:
	$(call log,INFO,Compiling gRPC protos ...)
	@for v in v3; do \
		$(python) -m grpc_tools.protoc \
			--proto_path=. \
			--python_out=. \
			--pyi_out=. \
			--grpc_python_out=. \
			./protos/$$v/*.proto; \
	done
	$(call log,INFO,gRPC compilation complete)

payload-specs-fetch:
	$(call log,INFO,Fetching payload specs submodule ...)
	@git submodule update --init --recursive --remote --merge
	$(call log,INFO,Payload specs fetched)

payload-specs-build:
	$(call log,INFO,Building payload specs library ...)
	@cd lib_relaysms_payload_specs && \
		cargo build --release
	$(call log,INFO,Payload specs built)

payload-specs-compile: payload-specs-fetch payload-specs-build
	$(call log,INFO,Compiling payload specs bindings ...)
	@cd lib_relaysms_payload_specs && \
		mkdir -p generated && \
		cargo run --bin uniffi_bindgen -- generate \
			--library target/release/librelaysms_spec_payload.so \
			--language python \
			--out-dir generated/ && \
		cp target/release/librelaysms_spec_payload.so generated/
	$(call log,INFO,Payload specs compiled)

build-setup: grpc-compile payload-specs-compile

migrate-up:
	$(call log,INFO,Running database migrations ...)
	@$(python) -m alembic upgrade head
	$(call log,INFO,Migrations complete)

grpc-server-start:
	$(call log,INFO,Starting gRPC server ...)
	@$(python) -u grpc_server.py

fastapi-server-start:
	$(call log,INFO,Starting FastAPI server ...)
	@$(python) -m uvicorn app:app --workers 1 --host $(grpc_host) --port $(fastapi_port)

celery-worker-start:
	$(call log,INFO,Starting Celery worker ...)
	@$(python) -m celery -A tasks.celery_app:celery_app worker \
		--loglevel=info \
		--without-gossip \
		--without-mingle \
		--without-heartbeat

celery-beat-start:
	$(call log,INFO,Starting Celery beat scheduler ...)
	@$(python) -m celery -A tasks.celery_app:celery_app beat --loglevel=info

smtp-listener-start:
	$(call log,INFO,Starting SMTP listener ...)
	@$(python) -u smtp_listener.py

run:
	@PYTHON=$(python) HOST=$(grpc_host) PORT=$(fastapi_port) ./scripts/run.sh
