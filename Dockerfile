FROM python:3.14.1-slim AS builder

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
COPY requirements.txt .
RUN --mount=type=cache,sharing=locked,target=/root/.cache/pip \
  /venv/bin/pip install --disable-pip-version-check -r requirements.txt

COPY . .
ENV PATH="/venv/bin:${PATH}"
RUN make build-setup


FROM python:3.14.1-slim

WORKDIR /publisher

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt \
  --mount=type=cache,sharing=locked,target=/var/lib/apt \
  apt-get update && apt-get install -y --no-install-recommends \
  libsqlcipher0 \
  git && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY --from=builder /publisher /publisher

RUN chmod +x /publisher/docker-entrypoint.sh

ENV PATH="/venv/bin:${PATH}"
ENV MODE=production

ENTRYPOINT ["/publisher/docker-entrypoint.sh"]
