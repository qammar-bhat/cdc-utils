FROM python:3.11.14-slim

WORKDIR /app

# Install dependencies first — this layer is cached unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download embedding model BEFORE copying source, so a code change does NOT
# re-trigger the ~430MB download — this layer is cached unless requirements change.
# Must match llm_profiles.json embedding_profile (LOCK-STEP CONTRACT #1).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='mixedbread-ai/mxbai-embed-large-v1')"

# Copy application code (.dockerignore keeps out .env, tests, cache etc.)
COPY . .

# Install the project so `indexer` is importable without sys.path hacks
RUN pip install --no-cache-dir -e .

# Run as non-root user for security
RUN adduser --disabled-password --gecos "" appuser
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 8090

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
