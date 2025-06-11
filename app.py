import pandas as pd
import numpy as np
import datetime
import time
import yfinance as yf
import requests

TELEGRAM_TOKEN = "7699600837:AAGYo_kYoCixTtWyQu1CYmFAJsFwIHXmjMQ"
CHAT_ID = "7811895611"
MAX_TRADES_PER_DAY = 2
TICKER = "^NSEI"
SL_PERCENT = 0.5
TARGET_PERCENT = 1.0

def get_live_data():
    df = yf.download(tickers=TICKER, period="2d", interval="15m", progress=False)
    return df.reset_index()

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_indicators(df):
    df['EMA_9'] = df['Close'].ewm(span=9).mean()
    df['EMA_21'] = df['Close'].ewm(span=21).mean()
    df['RSI'] = compute_rsi(df['Close'])
    df['Vol_MA5'] = df['Volume'].rolling(5).mean()
    return df

def detect_price_pattern(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    third = df.iloc[-3]
    if latest['High'] < prev['High'] and latest['Low'] > prev['Low']:
        return "Inside Bar"
    if latest['Close'] > max(prev['High'], third['High']):
        return "Breakout"
    if latest['Close'] < min(prev['Low'], third['Low']):
        return "Breakdown"
    if latest['Close'] < prev['Close'] and prev['Close'] > third['Close']:
        return "Pullback"
    return "No Pattern"

def get_atm_strike(price):
    return int(round(price / 50.0) * 50)

def fetch_option_price(strike, option_type="CE"):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers)
        res = session.get(url, headers=headers)
        data = res.json()

        for item in data["records"]["data"]:
            if item.get("strikePrice") == strike and option_type in item:
                return item[option_type]["lastPrice"]
        return None
    except Exception as e:
        print("⚠️ Option fetch error:", e)
        return None

def check_trade_signal(df):
    latest = df.iloc[-1]
    is_bullish = latest['EMA_9'] > latest['EMA_21'] and latest['RSI'] > 55
    is_bearish = latest['EMA_9'] < latest['EMA_21'] and latest['RSI'] < 45
    is_high_vol = latest['Volume'] > latest['Vol_MA5']
    pattern = detect_price_pattern(df)
    valid_pattern = pattern in ["Breakout", "Inside Bar", "Pullback", "Breakdown"]

    if is_bullish and is_high_vol and valid_pattern:
        return "BUY CALL", pattern
    elif is_bearish and is_high_vol and valid_pattern:
        return "BUY PUT", pattern
    return None, None

def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, data=payload)

def wait_for_exit(entry_price, sl, target, direction):
    while True:
        time.sleep(60)
        df = get_live_data()
        price = df['Close'].iloc[-1]
        if direction == "CALL":
            if price >= target:
                send_telegram_message(f"🎯 *Target Hit* at {price:.2f}. Exiting CALL.")
                break
            elif price <= sl:
                send_telegram_message(f"🛑 *Stop Loss Hit* at {price:.2f}. Exiting CALL.")
                break
        elif direction == "PUT":
            if price <= target:
                send_telegram_message(f"🎯 *Target Hit* at {price:.2f}. Exiting PUT.")
                break
            elif price >= sl:
                send_telegram_message(f"🛑 *Stop Loss Hit* at {price:.2f}. Exiting PUT.")
                break

def run_bot():
    trades = 0
    while trades < MAX_TRADES_PER_DAY:
        try:
            df = get_live_data()
            df = calculate_indicators(df)
            signal, pattern = check_trade_signal(df)

            if signal:
                spot = df['Close'].iloc[-1]
                strike = get_atm_strike(spot)
                sl = round(spot * (1 - SL_PERCENT / 100), 2) if "PUT" in signal else round(spot * (1 + SL_PERCENT / 100), 2)
                target = round(spot * (1 + TARGET_PERCENT / 100), 2) if "CALL" in signal else round(spot * (1 - TARGET_PERCENT / 100), 2)
                option_type = "CE" if "CALL" in signal else "PE"
                opt_price = fetch_option_price(strike, option_type)

                msg = (
                    f"📢 *{signal} Triggered*\n"
                    f"Pattern: {pattern}\n"
                    f"Time: {datetime.datetime.now().strftime('%H:%M')}\n"
                    f"Spot: {spot:.2f}\n"
                    f"ATM: {strike}{option_type}\n"
                    f"LTP: ₹{opt_price}\n"
                    f"SL: {sl}, Target: {target}"
                )
                send_telegram_message(msg)
                trades += 1
                wait_for_exit(spot, sl, target, "CALL" if "CALL" in signal else "PUT")
            time.sleep(900)
        except Exception as e:
            print("Bot error:", e)
            time.sleep(60)

# === Start
run_bot()
