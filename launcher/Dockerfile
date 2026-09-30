FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# Root deliberado (ADR 0028 §1): hablar con /var/run/docker.sock exige el
# gid del grupo "docker" del host, variable según la máquina — root evita
# tener que averiguarlo/sincronizarlo. El servicio no publica ningún puerto
# ni tiene autenticación de usuarios propia: toda su superficie de ataque
# son 4 endpoints internos, no expuestos fuera de la red de Docker.
CMD ["uvicorn", "launcher.main:app", "--host", "0.0.0.0", "--port", "9000"]
