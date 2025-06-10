FROM python:3.13.4-slim 

WORKDIR /publisher

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    default-libmysqlclient-dev \
    supervisor \
    curl \
    git \
    pkg-config && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --disable-pip-version-check --quiet --no-cache-dir -r requirements.txt

COPY . .

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN make build-setup

ENV MODE=production

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
