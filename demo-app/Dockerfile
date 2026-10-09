FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.34.0" prometheus-client==0.21.1
COPY app.py .
RUN useradd -u 10001 -m app
USER 10001
EXPOSE 8000
CMD ["python", "app.py"]
