FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir requests==2.32.5 \
    && useradd --create-home --uid 1000 runner
COPY --chown=runner:runner hunter.py /app/hunter.py
USER runner
CMD ["python", "-u", "/app/hunter.py"]
