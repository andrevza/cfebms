ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.12-alpine3.24@sha256:608cee238b1b779ef6ace48718d116d153b65d2361a2c458b31a9a627b2c4608
FROM ${BUILD_FROM} AS base

ARG BUILD_VERSION=unknown
ARG BUILD_ARCH=unknown
ARG BUILD_GIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ARG BUILD_SOURCE_STATE=unknown

LABEL org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIMESTAMP}" \
      org.opencontainers.image.source="https://github.com/andrevza/cfebms" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.type="app"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY run.sh /run.sh
COPY config.yaml /tmp/cfebms-config.yaml

ENV BUILD_GIT_SHA=${BUILD_GIT_SHA} \
    BUILD_TIMESTAMP=${BUILD_TIMESTAMP} \
    BUILD_SOURCE_STATE=${BUILD_SOURCE_STATE}

RUN python -m pip install --no-cache-dir . \
    && python -m cfebms.build_info \
    && rm /tmp/cfebms-config.yaml \
    && if [ -f /etc/alpine-release ]; then \
         addgroup -g 10001 cfebms \
         && adduser -D -h /home/cfebms -u 10001 -G cfebms cfebms; \
       else \
         groupadd --gid 10001 cfebms \
         && useradd --create-home --uid 10001 --gid cfebms cfebms; \
       fi \
    && chmod 755 /run.sh \
    && chown -R cfebms:cfebms /app

ENV BUILD_GIT_SHA= \
    BUILD_TIMESTAMP= \
    BUILD_SOURCE_STATE=

FROM base AS test

USER root
RUN python -m pip install --no-cache-dir '.[dev]'
COPY tests ./tests
COPY config.yaml repository.yaml build.yaml Dockerfile run.sh docker-compose.yml DOCS.md CHANGELOG.md icon.png logo.png ./
COPY .github/workflows/docker.yml ./.github/workflows/docker.yml
COPY docs/images/cfebms-banner.png ./docs/images/cfebms-banner.png
COPY translations ./translations
RUN chown -R cfebms:cfebms /app
USER root

ENTRYPOINT ["python", "-m", "pytest"]

FROM base AS runtime

CMD ["/run.sh", "service"]
