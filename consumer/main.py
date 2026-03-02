import os
import json
import time
import threading
import psycopg2
from psycopg2.extras import execute_values
from confluent_kafka import Consumer
from sentence_transformers import SentenceTransformer

KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "secretpostgres")
DB_NAME = os.environ.get("DB_NAME", "db")

print("Loading Embedding Model (all-MiniLM-L6-v2 for now)")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded")

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME
    )

kafka_config = {
    'bootstrap.servers': KAFKA_BROKER,
    'auto.offset.reset': 'earliest' # for older offline messages
}


def consume_prices():
    consumer = Consumer({**kafka_config, 'group.id': 'prices-consumer-group'})
    consumer.subscribe(['raw_prices'])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    batch_buffer = []
    BATCH_SIZE = 100

    print("Started listening to raw_prices topic")
    
    try:
        while True:
            msg = consumer.poll(1.0)
            
            if msg is None:
                if len(batch_buffer) > 0:
                    insert_price_batch(conn, cursor, batch_buffer)
                    batch_buffer.clear()
                continue
            
            if msg.error():
                print(f"Price Consumer Error: {msg.error()}")
                continue

            try:
                data = json.loads(msg.value().decode('utf-8'))
                batch_buffer.append((data['time'], data['symbol'], data['price'], data['volume']))
            except Exception as e:
                print(f"Error parsing price object message: {e}")

            if len(batch_buffer) >= BATCH_SIZE:
                insert_price_batch(conn, cursor, batch_buffer)
                batch_buffer.clear()
    finally:
        cursor.close()
        conn.close()
        consumer.close()

def insert_price_batch(conn, cursor, batch):
    query = "INSERT INTO raw_prices (time, symbol, price, volume) VALUES %s"
    try:
        execute_values(cursor, query, batch)
        conn.commit()
        print(f"[PRICES DB] Inserted batch of {len(batch)} prices")
    except Exception as e:
        print(f"[PRICES DB ERROR] Failed to insert prices: {e}")
        conn.rollback()



def consume_news():
    consumer = Consumer({**kafka_config, 'group.id': 'news-consumer-group'})
    consumer.subscribe(['financial_news'])
    
    conn = get_db_connection()
    cursor = conn.cursor()

    print("Started listening to financial_news topic")
    
    try:
        while True:
            msg = consumer.poll(1.0)
            
            if msg is None or msg.error():
                continue

            try:
                news = json.loads(msg.value().decode('utf-8'))
                
                # helps with context
                text_to_embed = f"{news['headline']}. {news.get('summary', '')}"
                vector = embedding_model.encode(text_to_embed).tolist()
                
                # the on conflict for no duplicate urls
                query = """
                    INSERT INTO financial_news (published_at, headline, summary, url, tickers, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING;
                """
                cursor.execute(query, (
                    news['published_at'], 
                    news['headline'], 
                    news.get('summary', ''), 
                    news['url'], 
                    news.get('tickers', []), 
                    str(vector)
                ))
                conn.commit()

                # print(f"[NEWS DB] Vectorized & Saved: {news['headline'][:20]}...")
            
            except Exception as e:
                print(f"Error processing news object message: {e}")
                conn.rollback()

    finally:
        cursor.close()
        conn.close()
        consumer.close()



if __name__ == '__main__':
    print("Starting Python Consumers")
    
    t1 = threading.Thread(target=consume_prices, daemon=True)
    t2 = threading.Thread(target=consume_news, daemon=True)
    
    t1.start()
    t2.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down consumers")