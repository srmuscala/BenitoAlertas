FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El bot no expone puertos, solo hace peticiones salientes.
CMD ["python", "main.py"]
