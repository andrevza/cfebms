ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY run.sh /run.sh

RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 cfebms \
    && chmod 755 /run.sh \
    && chown -R cfebms:cfebms /app

USER cfebms

FROM base AS test

USER root
RUN python -m pip install --no-cache-dir '.[dev]'
COPY tests ./tests
COPY config.yaml repository.yaml build.yaml Dockerfile run.sh DOCS.md icon.png logo.png ./
COPY docs/images/cfebms-banner.png ./docs/images/cfebms-banner.png
RUN chown -R cfebms:cfebms /app
USER cfebms

ENTRYPOINT ["python", "-m", "pytest"]

FROM base AS runtime

ENTRYPOINT ["/run.sh"]
CMD ["service"]
