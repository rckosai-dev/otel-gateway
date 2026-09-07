FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generator.py logs_gen.py traces_gen.py metrics_gen.py services.yaml ./

ENTRYPOINT ["python3", "generator.py"]
