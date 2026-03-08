FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/gtfs data/favorites

ENV PYTHONUNBUFFERED=1

CMD ["python", "run.py"]
