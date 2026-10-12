# Klaro hosted instance.
# python:3.12-slim satisfies the project's requires-python (>=3.11,<3.14);
# Playwright then pulls Chromium plus its OS dependencies.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && uv run --frozen --no-dev playwright install --with-deps chromium

# Vertex auth by default (no API key). To use the Gemini API instead, set
# GOOGLE_GENAI_USE_VERTEXAI=False and GOOGLE_API_KEY at deploy time.
ENV GOOGLE_GENAI_USE_VERTEXAI=True \
    GOOGLE_CLOUD_LOCATION=global \
    RATE_LIMIT_PER_MIN=20 \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uv run --frozen --no-dev uvicorn app.ambient_service:app --host 0.0.0.0 --port ${PORT:-8080}"]
