FROM python:3.11.10-slim

WORKDIR /app
COPY pyproject.toml ./
COPY fraudring ./fraudring
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    RESULTS_DIR=/results
EXPOSE 8000
CMD ["uvicorn", "fraudring.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
