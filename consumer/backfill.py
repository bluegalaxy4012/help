import os
import json
import finnhub
from datetime import datetime, timezone, timedelta
from confluent_kafka import Producer

KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "kafka:9092")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "d6iu3jhr01qleu95it4gd6iu3jhr01qleu95it50")

def run_backfill():
    print(f"Connecting to Kafka at {KAFKA_BROKER} for backfill")
    producer = Producer({'bootstrap.servers': KAFKA_BROKER})
    

    finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

    tickers = ["NVDA", "AAPL", "MSFT", "AMZN", "GLD", "SLV", "USO", "UNG", "HSY", "IBIT", "ETHA"]
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=7)
    
    _from = start_date.strftime("%Y-%m-%d")
    _to = end_date.strftime("%Y-%m-%d")

    print(f"Starting News Backfill ({_from} to {_to})")
    
    for ticker in tickers:
        try:
            news_items = finnhub_client.company_news(ticker, _from=_from, to=_to)
            
            for item in news_items:
                dt = datetime.fromtimestamp(item['datetime'], tz=timezone.utc)
                
                payload = {
                    "published_at": dt.isoformat(),
                    "headline": item['headline'],
                    "summary": item.get('summary', ''),
                    "url": item['url'],
                    "tickers": [ticker]
                }
                
                producer.produce("financial_news", value=json.dumps(payload).encode('utf-8'))
                producer.poll(0)
                
            print(f"Successfully backfilled {len(news_items)} articles for {ticker} (duplicates will be ignored)")
            
        except Exception as e:
            print(f"Failed to fetch Finnhub news for {ticker}, error: {e}")

    producer.flush()
    print("News Backfill complete")

if __name__ == "__main__":
    run_backfill()