FROM python:3.13-slim

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# model to cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY main.py .

CMD ["python", "main.py"]
