FROM python:3.15.0rc1-slim-bookworm AS builder

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
  make && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
  | sh -s -- -y --no-modify-path
ENV PATH="/root/.cargo/bin:${PATH}"

RUN python3 -m venv /venv
COPY requirements.txt requirements-observability.txt .
RUN --mount=type=cache,sharing=locked,target=/root/.cache/pip \
  /venv/bin/pip install --disable-pip-version-check \
  -r requirements.txt -r requirements-observability.txt

COPY . .
ENV PATH="/venv/bin:${PATH}"
# Submodule URL is SSH-based; rewrite to HTTPS since no SSH key is
# available in the build environment (same fix install.sh applies).
RUN git config --global url."https://github.com/".insteadOf "git@github.com:" \
  && make build-setup


FROM python:3.15.0rc1-slim-bookworm

WORKDIR /publisher

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt \
  --mount=type=cache,sharing=locked,target=/var/lib/apt \
  apt-get update && apt-get install -y --no-install-recommends \
  libsqlcipher0 \
  libmagic1 \
  git && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY --from=builder /publisher /publisher

RUN chmod +x /publisher/docker-entrypoint.sh /publisher/scripts/run.sh /publisher/scripts/otel-wrap.sh

ENV PATH="/venv/bin:${PATH}"
ENV MODE=production

ENTRYPOINT ["/publisher/docker-entrypoint.sh"]
