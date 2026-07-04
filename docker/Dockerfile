# python:3.12-slim-bookworm ships PostgreSQL 15 in the default apt repository.
# Debian bookworm does not package pgvector in the base repositories, so the
# extension is built from the upstream pgvector tag against PostgreSQL 15.
FROM python:3.12-slim-bookworm

ARG PGVECTOR_VERSION=v0.7.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql \
        postgresql-contrib \
        postgresql-server-dev-15 \
        build-essential \
        git \
        ca-certificates \
        curl \
    && git clone --depth 1 --branch "${PGVECTOR_VERSION}" https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector \
    && make -C /tmp/pgvector install \
    && rm -rf /tmp/pgvector \
    && apt-get purge -y --auto-remove \
        postgresql-server-dev-15 \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1002 planmgr \
    && useradd --uid 1002 --gid 1002 --home /var/planmgr --shell /usr/sbin/nologin planmgr

WORKDIR /build
COPY pyproject.toml /build/pyproject.toml
COPY plan_manager /build/plan_manager
RUN pip install --no-cache-dir .

COPY plan_manager_db/ /opt/plan_manager_db/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh

VOLUME ["/etc/planmgr", "/var/planmgr", "/var/log/planmgr"]

ENV PGDATA=/var/planmgr/postgres
ENV PATH=/usr/lib/postgresql/15/bin:$PATH

WORKDIR /var/planmgr

EXPOSE 8080

USER 1002:1002

# The health probe speaks whatever protocol server.protocol selects; the
# logic lives in /usr/local/bin/healthcheck.sh (http, https with -k, or
# mtls presenting the mounted client certificate).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
