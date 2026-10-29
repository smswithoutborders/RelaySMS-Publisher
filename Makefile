# SPDX-License-Identifier: GPL-3.0-only

SYSTEM_PYTHON ?= python3
PYTHON ?= venv/bin/python
CREDS_USER ?= dev
SPECS_DIR := lib_relaysms_payload_specs
SPECS_LIB := $(SPECS_DIR)/target/release/librelaysms_spec_payload.so

.PHONY: setup build protos specs migrate creds run test coverage test-sdk test-dialects test-e2e docs book book-serve check clean

## Set up a development checkout.
setup: venv/bin/python .env
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pre_commit install --install-hooks
	$(MAKE) build
	$(PYTHON) -m publisher config check
	$(MAKE) migrate

venv/bin/python:
	$(SYSTEM_PYTHON) -m venv venv

.env:
	install -m 600 template.env $@
	for key in DATABASE_ENCRYPTION_KEY DATABASE_FIELD_ENCRYPTION_KEY DATA_ENCRYPTION_KEY; do \
		sed -i.bak "s/^$$key=$$/$$key=$$(openssl rand -hex 32)/" $@; \
	done
	rm -f $@.bak

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

## Create an administrator credential named CREDS_USER and print its password once.
creds:
	$(PYTHON) -m publisher creds create --username $(CREDS_USER) --administrator

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

## Migrate and query SQLite and SQLCipher, and Postgres, MySQL and MariaDB in podman.
test-dialects:
	$(PYTHON) -m pytest tests/dialects $(PYTEST_ARGS)

## Install, update and uninstall in systemd containers with podman (slow, needs network).
test-e2e:
	$(PYTHON) -m pytest --noconftest tests/e2e $(PYTEST_ARGS)

## Regenerate docs/openapi.json from the REST app. A test fails when it's stale.
docs:
	$(PYTHON) -m publisher.api.rest.openapi

## Build the manual in docs/ into book/.
book:
	./scripts/build-book.sh

## Serve the manual on http://localhost:3000, rebuilding on changes.
book-serve:
	./scripts/build-book.sh --serve

check:
	$(PYTHON) -m pre_commit run --all-files

clean:
	rm -f protos/*/*_pb2.py protos/*/*_pb2.pyi protos/*/*_pb2_grpc.py
	rm -f $(SPECS_DIR)/generated/*.py $(SPECS_DIR)/generated/*.so
