import pandas as pd
import yfinance as yf
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION FROM ENVIRONMENT VARIABLES ---
# These will be loaded from GitHub Secrets
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# Settings (Defaults provided if not set)
ADX_THRESHOLD = int(os.getenv("ADX_THRESHOLD", 25))
DATA_FILE = "best_ema_results.csv"

# --- HELPER FUNCTIONS ---

def send_discord_alert(message):
    if not DISCORD_WEBHOOK_URL:
        return
    data = {"content": message}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        print(">> Discord alert sent.")
    except Exception as e:
        print(f"!! Discord Error: {e}")

def send_email_alert(subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print(">> Email alert sent.")
    except Exception as e:
        print(f"!! Email Error: {e}")

def calculate_indicators(df, fast_period, slow_period):
    df = df.copy()
    # EMAs
    df['Fast_EMA'] = df['Close'].ewm(span=fast_period, adjust=False).mean()
    df['Slow_EMA'] = df['Close'].ewm(span=slow_period, adjust=False).mean()
    
    # ADX
    df['UpMove'] = df['High'] - df['High'].shift(1)
    df['DownMove'] = df['Low'].shift(1) - df['Low']
    df['+DM'] = 0.0
    df['-DM'] = 0.0
    df.loc[(df['UpMove'] > df['DownMove']) & (df['UpMove'] > 0), '+DM'] = df['UpMove']
    df.loc[(df['DownMove'] > df['UpMove']) & (df['DownMove'] > 0), '-DM'] = df['DownMove']
    
    df['TR'] = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    
    df['TR14'] = df['TR'].ewm(alpha=1/14, adjust=False).mean()
    df['+DI14'] = 100 * (df['+DM'].ewm(alpha=1/14, adjust=False).mean() / df['TR14'])
    df['-DI14'] = 100 * (df['-DM'].ewm(alpha=1/14, adjust=False).mean() / df['TR14'])
    df['DX'] = 100 * abs(df['+DI14'] - df['-DI14']) / (df['+DI14'] + df['-DI14'])
    df['ADX'] = df['DX'].ewm(alpha=1/14, adjust=False).mean()
    
    return df

def main():
    print(f"--- Starting EMA Scanner (GitHub Actions) ---")
    
    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found. Make sure to upload it to the repo.")
        return

    # Load parameters
    try:
        ema_df = pd.read_csv(DATA_FILE)
        ema_df.columns = ema_df.columns.str.strip()
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    signals = []
    print(f"Scanning {len(ema_df)} tickers...")

    for index, row in ema_df.iterrows():
        ticker = row['Ticker']
        try:
            fast_period = int(row['Fast'])
            slow_period = int(row['Slow'])
        except ValueError:
            continue

        try:
            # Download data (buffer included)
            data = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=False)
            if len(data) < slow_period + 10:
                continue

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            data = calculate_indicators(data, fast_period, slow_period)
            
            # Check most recent closed candle
            today = data.iloc[-1]
            yesterday = data.iloc[-2]

            # Logic: Bullish Crossover + ADX Strength
            bullish_cross = (yesterday['Fast_EMA'] <= yesterday['Slow_EMA']) and \
                            (today['Fast_EMA'] > today['Slow_EMA'])
            
            strong_trend = today['ADX'] > ADX_THRESHOLD

            if bullish_cross and strong_trend:
                msg = (f"🚀 **{ticker}** | Price: ${today['Close']:.2f}\n"
                       f"Cross: {fast_period}/{slow_period} EMA | ADX: {today['ADX']:.1f}")
                print(msg)
                signals.append(msg)

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

    # Reporting
    if signals:
        report = "**DAILY EMA SCANNER REPORT**\n\n" + "\n".join(signals)
        print("\n" + report)
        send_discord_alert(report)
        send_email_alert(f"Scanner Found {len(signals)} Stocks", report)
    else:
        print("No signals found today.")

if __name__ == "__main__":
    main()