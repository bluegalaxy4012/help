import os
import time
import psycopg2
from datetime import datetime, timedelta, timezone

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "secretpostgres")
DB_NAME = os.environ.get("DB_NAME", "db")

TOP_CRYPTOS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "AVAX", "DOT", "LINK", "SHIB", "BCH", "LTC", "NEAR"]

SLEEP_SECONDS = 5


def get_db():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, dbname=DB_NAME)


def evaluate_alerts():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, symbol, price_change_percent, timeframe_minutes, volume_multiplier, volume_over, created_at "
        "FROM alerts WHERE is_active = TRUE;"
    )
    alerts = cursor.fetchall()

    for alert in alerts:
        alert_id, symbol, target_percent, tf_minutes, vol_mult, vol_over, created_at = alert

        # some casting problems with python-postgres
        target_percent = float(target_percent) if target_percent is not None else 0.0
        vol_mult = float(vol_mult) if vol_mult is not None else 0.0

        if created_at is None:
            created_at_param = datetime.now(timezone.utc) - timedelta(minutes=tf_minutes if tf_minutes and tf_minutes > 0 else 1)
        else:
            created_at_param = created_at

        db_symbol = symbol + "USDT" if symbol in TOP_CRYPTOS else symbol

        try:
            cursor.execute(
                "SELECT price FROM raw_prices WHERE symbol = %s ORDER BY time DESC LIMIT 1;",
                (db_symbol,),
            )
            current_row = cursor.fetchone()
            if not current_row:
                continue
            current_price = float(current_row[0])

            if target_percent is None:
                continue

            if target_percent < 0:
                cursor.execute(
                    "SELECT MAX(price) FROM raw_prices "
                    "WHERE symbol = %s AND time >= GREATEST(%s, NOW() - INTERVAL '1 minute' * %s);",
                    (db_symbol, created_at_param, tf_minutes),
                )
            else:
                cursor.execute(
                    "SELECT MIN(price) FROM raw_prices "
                    "WHERE symbol = %s AND time >= GREATEST(%s, NOW() - INTERVAL '1 minute' * %s);",
                    (db_symbol, created_at_param, tf_minutes),
                )

            ref_row = cursor.fetchone()
            if not ref_row or ref_row[0] is None:
                continue
            reference_price = float(ref_row[0])

            percent_change = ((current_price - reference_price) / reference_price) * 100

            # print(f"[{datetime.now().strftime('%H:%M:%S')}] {symbol} | Curr: ${current_price:.2f} | Max: ${reference_price:.2f} | Drop: {percent_change:.4f}% (Need: {target_percent}%)", flush=True)

            vol_condition_met = True
            actual_vol_mult = "N/A"

            if vol_mult is not None and vol_mult > 0.0:
                try:
                    tf = int(tf_minutes) if tf_minutes and int(tf_minutes) > 0 else 1
                except Exception:
                    tf = 1

                now = datetime.now(timezone.utc)
                recent_from = now - timedelta(minutes=tf)
                historical_from = now - timedelta(minutes=2 * tf)
                historical_to = recent_from

                # relative volume calc (tried but can be buggy)

                cursor.execute(
                    "SELECT COALESCE(SUM(volume),0), COALESCE(SUM(price * volume),0), COALESCE(COUNT(*),0) "
                    "FROM raw_prices WHERE symbol = %s AND time >= %s AND time < %s;",
                    (db_symbol, recent_from, now),
                )
                recent_sum_vol, recent_sum_dollar, recent_count = cursor.fetchone()
                recent_sum_vol = float(recent_sum_vol or 0.0)
                recent_sum_dollar = float(recent_sum_dollar or 0.0)
                recent_count = int(recent_count or 0)


                cursor.execute(
                    "SELECT COALESCE(SUM(volume),0), COALESCE(SUM(price * volume),0), COALESCE(COUNT(*),0) "
                    "FROM raw_prices WHERE symbol = %s AND time >= %s AND time < %s;",
                    (db_symbol, historical_from, historical_to),
                )
                hist_sum_vol, hist_sum_dollar, hist_count = cursor.fetchone()
                hist_sum_vol = float(hist_sum_vol or 0.0)
                hist_sum_dollar = float(hist_sum_dollar or 0.0)
                hist_count = int(hist_count or 0)

                use_dollar = False # if you wish to use dollar volume
                recent_baseline = recent_sum_dollar if use_dollar else recent_sum_vol
                hist_baseline = hist_sum_dollar if use_dollar else hist_sum_vol


                # sanity thresholds 
                MIN_HIST_VOL = 1e-6
                MIN_HIST_COUNT = 3
                MIN_RECENT_ABS_VOL = 1e-6

                actual_vol_mult = 0.0
                vol_condition_met = True

                if hist_baseline <= MIN_HIST_VOL or hist_count < MIN_HIST_COUNT:
                    if recent_baseline <= MIN_RECENT_ABS_VOL:
                        actual_vol_mult = 0.0
                    else:
                        actual_vol_mult = float("inf")
                else:
                    actual_vol_mult = recent_baseline / hist_baseline

                if vol_over:
                    vol_condition_met = actual_vol_mult >= vol_mult
                else:
                    vol_condition_met = actual_vol_mult <= vol_mult


                # just for print
                if actual_vol_mult == float("inf"):
                    actual_vol_display = "inf (hist nearly 0)"
                else:
                    actual_vol_display = f"{actual_vol_mult:.2f}"

            else:
                vol_condition_met = True
                actual_vol_display = "N/A"


            alert_condition_met = False
            threshold_factor = 1.0 + (target_percent / 100.0)
            threshold_price = reference_price * threshold_factor

            if target_percent < 0:
                alert_condition_met = current_price <= threshold_price
            else:
                alert_condition_met = current_price >= threshold_price

            if alert_condition_met and vol_condition_met:
                actual_vol_display = f"{actual_vol_mult:.2f}" if isinstance(actual_vol_mult, float) else actual_vol_mult
                print(
                    f"[ALERT] Alert #{alert_id} triggered! {symbol} — current {current_price} vs ref {reference_price} "
                    f"-> {percent_change:.2f}% (Target: {target_percent}%) | Vol Mult: {actual_vol_display}",
                    flush=True,
                )

                # prevent spam
                cursor.execute("UPDATE alerts SET is_active = FALSE WHERE id = %s;", (alert_id,))
                conn.commit()

        except Exception as e:
            print(f"Error processing alert {alert_id} for {symbol}: {e}", flush=True)
            conn.rollback()

    cursor.close()
    conn.close()


if __name__ == "__main__":
    time.sleep(15) # TO FIX TO WAIT FOR DB TO BE READY
    print("Starting Alert Worker", flush=True)
    while True:
        try:
            evaluate_alerts()
        except Exception as e:
            print(f"Alert loop Error: {e}", flush=True)

        time.sleep(SLEEP_SECONDS)