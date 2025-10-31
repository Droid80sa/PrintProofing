FROM python:3.11-slim

WORKDIR /app

COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser --disabled-password --gecos '' appuser

COPY . .

RUN chown -R appuser /app
RUN mkdir -p /mnt/proofs && chown appuser:appuser /mnt/proofs

USER appuser

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app.app:app"]
