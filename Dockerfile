FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

COPY requirements-worker.txt ./
RUN pip install --no-cache-dir -r requirements-worker.txt

COPY . .

RUN chown -R pwuser:pwuser /app
USER pwuser

CMD ["python", "worker.py"]
