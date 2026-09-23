FROM python:3.12-slim
WORKDIR /app
COPY deploy/cloudru_reasoning_gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY deploy/cloudru_reasoning_gateway/app.py /app/app.py
ENV PORT=8080
EXPOSE 8080
CMD ["python", "app.py"]
