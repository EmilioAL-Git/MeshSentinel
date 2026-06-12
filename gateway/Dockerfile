FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# El acceso a /dev/ttyUSB* exige pertenecer al grupo dialout (gid 20 en Debian)
RUN useradd --create-home --uid 1000 gateway && usermod -aG dialout gateway
USER gateway

CMD ["python", "-m", "gateway.main"]
