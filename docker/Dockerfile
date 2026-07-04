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

RUN groupadd --gid 990 planmgr \
    && useradd --uid 990 --gid 990 --home /var/planmgr --shell /usr/sbin/nologin planmgr

WORKDIR /build
COPY pyproject.toml /build/pyproject.toml
COPY plan_manager /build/plan_manager
RUN pip install --no-cache-dir .

COPY plan_manager_db/ /opt/plan_manager_db/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

VOLUME ["/etc/planmgr", "/var/planmgr", "/var/log/planmgr"]

ENV PGDATA=/var/planmgr/postgres

EXPOSE 8080

USER 990:990

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
