FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    RISKLENS_DATABASE_URL=sqlite:///./data/risklens.sqlite3

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY app ./app
COPY src ./src
COPY public ./public
COPY research ./research
COPY artifacts/.gitkeep ./artifacts/.gitkeep
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --create-home --uid 10001 risklens \
    && mkdir -p /app/data /app/artifacts \
    && chown -R risklens:risklens /app
USER risklens
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
