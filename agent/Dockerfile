FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
ENV PYTHONPATH=/app/src
RUN useradd -u 10001 -m healer && mkdir -p /data/incidents && chown -R healer /data
USER 10001
EXPOSE 8080
CMD ["uvicorn", "healer.main:app", "--host", "0.0.0.0", "--port", "8080"]
