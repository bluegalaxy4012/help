import os
import time
import psycopg2
from datetime import datetime

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "secretpostgres")
DB_NAME = os.environ.get("DB_NAME", "db")

def get_db():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

def evaluate_alerts():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, symbol, price_change_pct, timeframe_hours, volume_multiplier FROM active_alerts WHERE is_active = TRUE;")
    alerts = cursor.fetchall()
    
    for alert in alerts:
        alert_id, symbol, target_percent, tf_hours, vol_mult = alert
        
        try:
            cursor.execute("SELECT price FROM raw_prices WHERE symbol = %s ORDER BY time DESC LIMIT 1;", (symbol,))
            current_row = cursor.fetchone()
            if not current_row:
                continue
            current_price = current_row[0]
            
            # last price from at least tf_hours ago, handling some edge cases
            cursor.execute(f"SELECT price FROM raw_prices WHERE symbol = %s AND time <= NOW() - INTERVAL '{tf_hours} hours' ORDER BY time DESC LIMIT 1;", (symbol,))
            past_row = cursor.fetchone()
            if not past_row:
                continue
            past_price = past_row[0]


            percent_change = ((current_price - past_price) / past_price) * 100


            cursor.execute("SELECT COALESCE(SUM(volume), 0) FROM raw_prices WHERE symbol = %s AND time >= NOW() - INTERVAL '1 hour';", (symbol,))
            recent_vol = cursor.fetchone()[0]
            
            cursor.execute(f"SELECT COALESCE(SUM(volume), 0) FROM raw_prices WHERE symbol = %s AND time >= NOW() - INTERVAL '{tf_hours + 1} hours' AND time < NOW() - INTERVAL '1 hour';", (symbol,))
            historical_vol_total = cursor.fetchone()[0]
            avg_historical_vol = historical_vol_total / tf_hours if tf_hours > 0 else 0
            
            actual_vol_mult = (recent_vol / avg_historical_vol) if avg_historical_vol > 0 else 0



            alert_condition_met = False
            if target_percent < 0 and percent_change <= target_percent:
                alert_condition_met = True
            elif target_percent > 0 and percent_change >= target_percent:
                alert_condition_met = True
                
            if alert_condition_met and actual_vol_mult >= vol_mult:
                print(f"[ALERT] {symbol} changed by {percent_change:.2f}% (Target: {target_percent}%) with {actual_vol_mult:.2f}x Volume", flush=True)
                
                # prevent spam for now
                cursor.execute("UPDATE active_alerts SET is_active = FALSE WHERE id = %s;", (alert_id,))
                conn.commit()

        except Exception as e:
            print(f"Error processing alert {alert_id} for {symbol}: {e}", flush=True)
            conn.rollback()

    cursor.close()
    conn.close()

if __name__ == "__main__":
    print("Starting Alert Worker", flush=True)
    while True:
        try:
            evaluate_alerts()
        except Exception as e:
            print(f"Alert loop Error: {e}", flush=True)
        
        
        time.sleep(60)