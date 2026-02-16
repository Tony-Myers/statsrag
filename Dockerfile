FROM python:3.11-slim

WORKDIR /app

# Copy project metadata first for better layer caching
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY docs ./docs

RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir -e .

EXPOSE 8501
CMD ["streamlit", "run", "/app/src/statsrag/ui_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
