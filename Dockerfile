FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md requirements.lock.txt ./
COPY sales_intelligence ./sales_intelligence
RUN pip install --no-cache-dir -r requirements.lock.txt && pip install --no-cache-dir --no-deps .
COPY scripts ./scripts
RUN useradd --create-home --uid 10001 sales && mkdir /data && chown sales:sales /data
USER sales
EXPOSE 8000
CMD ["python", "scripts/serve.py"]
