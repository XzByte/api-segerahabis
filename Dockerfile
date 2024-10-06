FROM python:3.9-slim

WORKDIR /app

RUN pip install --no-cache-dir virtualenv
RUN virtualenv .

COPY requirements.txt .
RUN . bin/activate && pip install --no-cache-dir -r requirements.txt

ENV DB_URL=$DB_URL
ENV DB_NAME=$DB_NAME
ENV DB_USER=$DB_USER
ENV DB_PASSWORD=$DB_PASS
ENV DB_PORT=$DB_PORT
ENV SECRET_KEY=$SECRET_KEY

COPY . .

EXPOSE 80
CMD ["/bin/bash", "-c", ". bin/activate && uvicorn main:app --host 0.0.0.0 --port 80"]
