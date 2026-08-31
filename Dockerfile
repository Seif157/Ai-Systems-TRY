# syntax=docker/dockerfile:1.19@sha256:b6afd42430b15f2d2a4c5a02b919e98a525b785b1aaff16747d2f623364e39b6

ARG SOURCE_DATE_EPOCH=1735689600
ARG OCI_SOURCE=https://github.com/Seif157/Ai-Systems-TRY
ARG OCI_REVISION=development-uncommitted
FROM ghcr.io/astral-sh/uv@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 AS uv
FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS builder
WORKDIR /build
ENV UV_NO_CACHE=1 UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY docs ./docs
RUN uv sync --locked --no-dev --no-editable \
    && uv build --wheel --no-sources \
    && uv pip install --python /opt/venv/bin/python --no-deps --force-reinstall dist/*.whl \
    && rm /opt/venv/lib/python3.12/site-packages/erp_ai_platform-0.1.0.dist-info/uv_cache.json \
    && sed -i '/uv_cache.json/d' /opt/venv/lib/python3.12/site-packages/erp_ai_platform-0.1.0.dist-info/RECORD

FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS runtime
ARG OCI_SOURCE
ARG OCI_REVISION
LABEL org.opencontainers.image.source="${OCI_SOURCE}" \
      org.opencontainers.image.revision="${OCI_REVISION}" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="Proprietary"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 TMPDIR=/tmp
ADD --checksum=sha256:a5592b5cf276bc7a30ac7b161d46446085490b640faa1f839ea98eb15aacad31 https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/libcrypto3-3.5.8-r0.apk /tmp/apks/libcrypto3-3.5.8-r0.apk
ADD --checksum=sha256:f80b76cb5e5a52cfc1ced08f8dc3022adc0ce0a3d6e7741976731b22c71fe310 https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/libssl3-3.5.8-r0.apk /tmp/apks/libssl3-3.5.8-r0.apk
ADD --checksum=sha256:414be12c879052f4614a42a10fc12af67a88ba49e8e1e33f78cd9ddbbdb13fee https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/sqlite-libs-3.53.4-r0.apk /tmp/apks/sqlite-libs-3.53.4-r0.apk
ADD --checksum=sha256:770d92f5134d2ee59182eeb3f3b95356c37886fa5ff796c50d8ba515a6b3c6d3 https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/libpq-18.6-r0.apk /tmp/apks/libpq-18.6-r0.apk
RUN --network=none apk verify /tmp/apks/*.apk \
    && apk add --no-network --no-cache --repositories-file /dev/null /tmp/apks/*.apk \
    && rm -f /var/log/apk.log \
    && rm -f /tmp/apks/*.apk \
    && rmdir /tmp/apks \
    && addgroup -g 10001 -S erpai \
    && adduser -u 10001 -S -D -H -h /nonexistent -s /sbin/nologin -G erpai erpai
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
USER 10001:10001
WORKDIR /nonexistent
EXPOSE 8080
ENTRYPOINT ["erp-ai-serve"]
