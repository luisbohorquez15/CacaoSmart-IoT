FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cacaosmart ./cacaosmart
COPY datasets/data/historico_clima_cosecha_2025.csv datasets/data/curva_ideal_secado.csv ./datasets/data/
USER nobody
CMD ["python", "-m", "cacaosmart.run_twins"]
