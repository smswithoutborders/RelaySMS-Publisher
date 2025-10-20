FROM python:3.14.0-slim 

WORKDIR /publisher

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt \
    --mount=type=cache,sharing=locked,target=/var/lib/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    default-libmysqlclient-dev \
    supervisor \
    curl \
    git \
    vim \
    pkg-config && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN --mount=type=cache,sharing=locked,target=/root/.cache/pip \
    pip install --disable-pip-version-check -r requirements.txt

COPY . .

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN make build-setup

ENV MODE=production

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
