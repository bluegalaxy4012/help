FROM python:3.13-slim

COPY requirements.txt .

# optional but image is way smaller with cpu only torch
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# model to cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY main.py .
COPY backfill.py .
COPY alerter.py .

CMD ["sh", "-c", "python backfill.py && python main.py"]
