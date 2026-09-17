FROM python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive
ARG ARISSTO_SYNC_RELEASE=unversioned

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg unixodbc \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
       | gpg --dearmor -o /etc/apt/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
       -o /etc/apt/sources.list.d/microsoft-prod.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/arissto-sync

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY arissto_sync ./arissto_sync
COPY config ./config
COPY migration-services ./migration-services
COPY workflows ./workflows

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin arissto-sync \
    && install -d -o arissto-sync -g arissto-sync -m 0750 /var/lib/arissto-sync

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARISSTO_SYNC_RELEASE=${ARISSTO_SYNC_RELEASE} \
    ARISSTO_SYNC_STATE=/var/lib/arissto-sync/state.sqlite3

USER 10001:10001
VOLUME ["/var/lib/arissto-sync"]

ENTRYPOINT ["python", "-m", "arissto_sync.cli"]
CMD ["health"]
