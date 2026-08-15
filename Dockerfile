# Multi-stage: dependencies are built once and only the resulting virtualenv is
# copied forward, so compilers and build caches never reach the runtime image.

FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY alembic.ini docker-entrypoint.sh ./

RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 1000 quartermaster \
    && chown -R quartermaster:quartermaster /app
USER quartermaster

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
