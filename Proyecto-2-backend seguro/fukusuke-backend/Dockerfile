FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common common
COPY auth_service auth_service
COPY gateway gateway
COPY inventory inventory
COPY clients clients
COPY orders orders
COPY payments payments
COPY graphql_gateway graphql_gateway
RUN useradd -m app && mkdir /data && chown app /data
USER app
