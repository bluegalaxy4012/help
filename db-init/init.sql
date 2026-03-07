CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE raw_prices (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(15) NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL
);

CREATE INDEX ON raw_prices (symbol, time DESC);

SELECT create_hypertable('raw_prices', 'time');

CREATE TABLE financial_news (
    id SERIAL PRIMARY KEY,
    published_at TIMESTAMPTZ NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT UNIQUE NOT NULL,
    tickers VARCHAR(10)[],
    embedding vector(384)
);

CREATE INDEX ON financial_news USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);


CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 0,
    symbol VARCHAR(15) NOT NULL,
    price_change_percent NUMERIC NOT NULL,
    timeframe_minutes INTEGER NOT NULL,
    volume_multiplier NUMERIC DEFAULT 0.0,
    volume_over BOOLEAN DEFAULT True,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_triggered_at TIMESTAMP WITH TIME ZONE
);
