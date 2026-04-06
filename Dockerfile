FROM python:3.12-slim

WORKDIR /app

# Deps do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Porta padrão
EXPOSE 8010

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8010/api/health || exit 1

# Rodar
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
