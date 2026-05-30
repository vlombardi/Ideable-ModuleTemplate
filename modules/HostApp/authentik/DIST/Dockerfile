FROM python:3.11-alpine

WORKDIR /bootstrap

RUN pip install --no-cache-dir psycopg2-binary PyYAML

COPY bootstrap_authentik.py /bootstrap/bootstrap_authentik.py

CMD ["python", "bootstrap_authentik.py"]
