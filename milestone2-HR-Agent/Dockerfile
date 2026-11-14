# Starter: lengkapi image aplikasi untuk FastAPI DAN Streamlit pada Compose serta Render deployment.
# Build tidak boleh membutuhkan OPENAI_API_KEY; konfigurasi model diberikan saat runtime.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY data/ ./data/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY app.py app2.py ui_contract.py demo_personas.json pyproject.toml README.md ./
COPY Dockerfile /app/Dockerfile
COPY ui/ ./ui/
COPY public/ ./public/
COPY web/ ./web/

RUN chmod +x ./scripts/*.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "src.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
