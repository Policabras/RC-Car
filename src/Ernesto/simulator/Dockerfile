FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY simulador.py .

CMD ["python", "simulador.py"]