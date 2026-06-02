python=python3
PROTO_DIR=protos/v1
CURRENT_BRANCH=$(shell git branch --show-current)

define log_message
	@echo "[$(shell date +'%Y-%m-%d %H:%M:%S')] - $1"
endef

define download-proto
	$(call log_message,INFO - Downloading $(PROTO_URL) to $@ ...)
	@mkdir -p $(dir $@) && \
	curl -o $@ -L $(PROTO_URL)
	$(call log_message,INFO - $@ downloaded successfully!)
endef

protos/v%/vault.proto:
	$(eval PROTO_URL := $(PROTO_URL))
	$(call download-proto)

vault-proto: 
	@for v in v1 v2; do \
		rm -f "protos/$$v/vault.proto"; \
		$(MAKE) PROTO_URL=https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Vault/$(CURRENT_BRANCH)/protos/$$v/vault.proto \
		protos/$$v/vault.proto; \
	done

grpc-compile:
	$(call log_message,[INFO] Compiling gRPC protos ...)
	@for v in v1 v2; do \
		$(python) -m grpc_tools.protoc \
			--proto_path=. \
			--python_out=. \
			--pyi_out=. \
			--grpc_python_out=. \
			./protos/$$v/*.proto ; \
	done
	$(call log_message,[INFO] gRPC Compilation complete!)

grpc-server-start:
	$(call log_message,INFO - Starting gRPC server ...)
	@$(python) -u grpc_server.py
	$(call log_message,INFO - gRPC server started successfully.)

payload-specs-fetch:
	$(call log_message,INFO - Fetching payload specifications library dependencies ...)
	@ git submodule update --init --recursive --remote --merge
	$(call log_message,INFO - Payload specifications library fetched successfully!)

payload-specs-build:
	$(call log_message,INFO - Building payload specifications library ...)
	@cd lib_relaysms_payload_specs && \
		cargo clean && \
		rm -rf generated/* && \
		rm -rf target/ && \
		cargo build --release
	$(call log_message,INFO - Payload specifications library built successfully!)

payload-specs-compile: payload-specs-fetch payload-specs-build
	$(call log_message,INFO - Compiling payload specifications ...)
	@cd lib_relaysms_payload_specs && \
		cargo run --bin uniffi_bindgen -- generate \
	  --library target/release/librelaysms_spec_payload.so \
	  --language python \
	  --out-dir generated/ && \
		cp target/release/librelaysms_spec_payload.so generated/
	$(call log_message,INFO - Payload specifications compiled successfully!)

build-setup: vault-proto grpc-compile
