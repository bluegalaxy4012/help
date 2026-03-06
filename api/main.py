import os
import strawberry
from fastapi import FastAPI
import psycopg2
from sentence_transformers import SentenceTransformer
from typing import List
from strawberry.fastapi import GraphQLRouter
import uvicorn

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "secretpostgres")
DB_NAME = os.environ.get("DB_NAME", "db")

embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

def get_db():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

@strawberry.type
class AlertObject:
    id: int
    symbol: str
    price_change_percent: float
    timeframe_hours: float

@strawberry.type
class Mutation:
    @strawberry.mutation
    def create_alert(
        self, 
        symbol: str, 
        price_change_percent: float, 
        timeframe_hours: float, 
        volume_multiplier: float = 1.0
    ) -> AlertObject:
        conn = get_db()
        cursor = conn.cursor()
        
        # for now uid is 0 since no auth
        query = """
            INSERT INTO active_alerts (user_id, symbol, price_change_pct, timeframe_hours, volume_multiplier)
            VALUES (0, %s, %s, %s, %s) RETURNING id;
        """
        cursor.execute(query, (symbol.upper(), price_change_percent, timeframe_hours, volume_multiplier))
        alert_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()

        return AlertObject(
            id=alert_id, 
            symbol=symbol.upper(), 
            price_change_percent=price_change_percent, 
            timeframe_hours=timeframe_hours
        )


@strawberry.type
class PriceObject:
    time: str
    symbol: str
    price: float
    volume: float

@strawberry.type
class NewsObject:
    headline: str
    summary: str
    url: str
    relevance_score: float

@strawberry.type
class Query:
    @strawberry.field
    def get_latest_prices(self, symbol: str, limit: int = 5) -> List[PriceObject]:
        conn = get_db()
        
        cursor = conn.cursor()
        query = "SELECT time, symbol, price, volume FROM raw_prices WHERE symbol = %s ORDER BY time DESC LIMIT %s;"
        cursor.execute(query, (symbol, limit))

        rows = cursor.fetchall()
        conn.close()

        return [PriceObject(time=str(row[0]), symbol=row[1], price=row[2], volume=row[3]) for row in rows]

    @strawberry.field
    def ask_ai_news(self, question: str, limit: int = 3) -> List[NewsObject]:
        question_vector = embedding_model.encode(question).tolist()
        conn = get_db()

        cursor = conn.cursor()
        query = """
            SELECT headline, summary, url, 1 - (embedding <=> %s::vector) AS relevance 
            FROM financial_news 
            ORDER BY embedding <=> %s::vector 
            LIMIT %s;
        """
        cursor.execute(query, (str(question_vector), str(question_vector), limit))

        rows = cursor.fetchall()
        conn.close()

        return [NewsObject(headline=row[0], summary=row[1], url=row[2], relevance_score=row[3]) for row in rows]

schema = strawberry.Schema(query=Query, mutation=Mutation)
app = FastAPI()
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)