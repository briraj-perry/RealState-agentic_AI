FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.prod.lock ./
RUN pip install --no-cache-dir -r requirements.prod.lock
COPY pyproject.toml ./
COPY estate_ai ./estate_ai
RUN pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 estate \
    && chown estate:estate /app
USER estate
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn estate_ai.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
