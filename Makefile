# SPDX-License-Identifier: GPL-3.0-only

PYTHON ?= python3
SPECS_DIR := lib_relaysms_payload_specs
SPECS_LIB := $(SPECS_DIR)/target/release/librelaysms_spec_payload.so

.PHONY: build protos specs migrate run test coverage test-sdk test-dialects test-e2e docs check clean

## Generate the gRPC code and the payload-specs bindings.
build: protos specs

protos:
	$(PYTHON) -m grpc_tools.protoc --proto_path=. --python_out=. --pyi_out=. \
		--grpc_python_out=. protos/*/*.proto

## Build the pinned payload-specs commit and generate its Python bindings.
specs:
	git submodule update --init --recursive
	cd $(SPECS_DIR) && cargo build --release
	mkdir -p $(SPECS_DIR)/generated
	cd $(SPECS_DIR) && cargo run --bin uniffi_bindgen -- generate \
		--library target/release/librelaysms_spec_payload.so \
		--language python --out-dir generated/
	cp $(SPECS_LIB) $(SPECS_DIR)/generated/

migrate:
	$(PYTHON) -m alembic upgrade head

## Start every service in the foreground.
run:
	PYTHON=$(PYTHON) ./scripts/run.sh

test:
	$(PYTHON) -m pytest $(PYTEST_ARGS)

## Run the suite and list the lines no test runs.
coverage:
	$(PYTHON) -m pytest --cov $(PYTEST_ARGS)

## Test the adapter SDK in sdk/.
test-sdk:
	$(PYTHON) -m pytest -c sdk/pyproject.toml sdk/tests sdk/examples $(PYTEST_ARGS)

## Migrate and query SQLite, SQLCipher, and Postgres, MySQL and MariaDB in podman.
test-dialects:
	$(PYTHON) -m pytest tests/dialects $(PYTEST_ARGS)

## Install and update in a systemd container with podman (slow, needs network).
test-e2e:
	$(PYTHON) -m pytest --noconftest tests/e2e $(PYTEST_ARGS)

## Regenerate docs/openapi.json from the REST app. A test fails when it's stale.
docs:
	$(PYTHON) -m publisher.api.rest.openapi

check:
	$(PYTHON) -m pre_commit run --all-files

clean:
	rm -f protos/*/*_pb2.py protos/*/*_pb2.pyi protos/*/*_pb2_grpc.py
	rm -f $(SPECS_DIR)/generated/*.py $(SPECS_DIR)/generated/*.so
