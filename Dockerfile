ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY run.sh /run.sh

RUN python -m pip install --no-cache-dir . \
    && if [ -f /etc/alpine-release ]; then \
         addgroup -g 10001 cfebms \
         && adduser -D -h /home/cfebms -u 10001 -G cfebms cfebms; \
       else \
         groupadd --gid 10001 cfebms \
         && useradd --create-home --uid 10001 --gid cfebms cfebms; \
       fi \
    && chmod 755 /run.sh \
    && chown -R cfebms:cfebms /app

FROM base AS test

USER root
RUN python -m pip install --no-cache-dir '.[dev]'
COPY tests ./tests
COPY config.yaml repository.yaml build.yaml Dockerfile run.sh docker-compose.yml DOCS.md icon.png logo.png ./
COPY docs/images/cfebms-banner.png ./docs/images/cfebms-banner.png
RUN chown -R cfebms:cfebms /app
USER root

ENTRYPOINT ["python", "-m", "pytest"]

FROM base AS runtime

CMD ["/run.sh", "service"]
