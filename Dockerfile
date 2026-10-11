# syntax=docker/dockerfile:1

# ---- build stage: install the app and its dependencies into a virtualenv
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /src
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# ---- runtime stage
FROM python:3.12-slim AS runtime

# System libraries WeasyPrint needs for PDF export, plus a basic font.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
      libfontconfig1 fonts-dejavu-core shared-mime-info \
 && rm -rf /var/lib/apt/lists/*

# Non-root user. uid/gid 568 is the default "apps" user on TrueNAS SCALE.
RUN groupadd --gid 568 planner \
 && useradd --uid 568 --gid 568 --no-create-home --home-dir /data --shell /usr/sbin/nologin planner \
 && mkdir /data && chown planner:planner /data

COPY --from=build /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLANNER_DATA_DIR=/data \
    PLANNER_PAGE_SIZE=Letter \
    PORT=8080 \
    HOME=/data \
    XDG_CACHE_HOME=/data/.cache

# All state (SQLite database, exports, caches) lives here and nowhere else.
VOLUME ["/data"]
EXPOSE 8080
USER planner
WORKDIR /data

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=4)"]

# Migrations run automatically when the app starts.
CMD ["planner", "serve", "--host", "0.0.0.0"]
