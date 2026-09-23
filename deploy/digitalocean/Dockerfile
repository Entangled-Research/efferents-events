# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 efferents \
    && useradd --uid 10001 --gid 10001 --home-dir /data/home --no-create-home efferents \
    && install -d -o 10001 -g 10001 \
        /data /data/home /data/efferents /data/submissions /data/cache /data/cache/matplotlib

WORKDIR /opt/efferents
# The root .dockerignore allows only framework code, package metadata, and
# this one offline example. Private labs, credentials, and Git never enter
# the build context. Popper Probe is a separately installed dependency.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY efferents/ ./efferents/
COPY docs/prototypes/event-network.html ./docs/prototypes/event-network.html
COPY examples/smoke-lab/ ./examples/smoke-lab/
RUN uv venv /opt/venv \
    && uv build --wheel --out-dir /opt/efferents/dist \
    && chmod 644 /opt/efferents/dist/*.whl \
    && uv pip install --no-cache --python /opt/venv/bin/python /opt/efferents/dist/*.whl

ENV EFFERENTS_INSTALL_WHEEL=/opt/efferents/dist/efferents-0.1.4-py3-none-any.whl \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data/home \
    XDG_CACHE_HOME=/data/cache \
    MPLCONFIGDIR=/data/cache/matplotlib \
    EFFERENTS_HOME=/data/efferents \
    POPPER_PROBE_REPO=/data/popper-probe

USER 10001:10001
WORKDIR /data
CMD ["efferents", "serve", "--no-open", "--port", "8800"]
