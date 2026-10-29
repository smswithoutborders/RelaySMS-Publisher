FROM python:3.14.7-slim-bookworm AS builder

WORKDIR /publisher

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt \
  --mount=type=cache,sharing=locked,target=/var/lib/apt \
  apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  python3-dev \
  libsqlcipher-dev \
  pkg-config \
  curl \
  git \
  make \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
  | sh -s -- -y --no-modify-path
ENV PATH="/root/.cargo/bin:${PATH}"

# The venv lives outside /publisher, linked to where make and scripts/run.sh
# look for it.
RUN python3 -m venv /venv && ln -s /venv venv
COPY requirements.txt requirements-observability.txt ./
COPY sdk ./sdk
RUN --mount=type=cache,sharing=locked,target=/root/.cache/pip \
  /venv/bin/pip install --disable-pip-version-check \
  -r requirements-observability.txt

COPY . .
RUN --mount=type=cache,sharing=locked,target=/root/.cargo/registry \
  --mount=type=cache,sharing=locked,target=/root/.cargo/git \
  --mount=type=cache,sharing=locked,target=/publisher/lib_relaysms_payload_specs/target \
  git config --global url."https://github.com/".insteadOf "git@github.com:" \
  && make build


FROM python:3.14.7-slim-bookworm

WORKDIR /publisher

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt \
  --mount=type=cache,sharing=locked,target=/var/lib/apt \
  apt-get update && apt-get install -y --no-install-recommends \
  libsqlcipher0 \
  libmagic1 \
  git \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY --from=builder /publisher /publisher

RUN chmod +x /publisher/docker-entrypoint.sh /publisher/scripts/run.sh /publisher/scripts/otel-wrap.sh

ENV PATH="/venv/bin:${PATH}"

ENTRYPOINT ["/publisher/docker-entrypoint.sh"]
