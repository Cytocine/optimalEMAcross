import pandas as pd
import yfinance as yf
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# =========================================================
# ENVIRONMENT VARIABLES (GitHub Secrets)
# =========================================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

ADX_THRESHOLD = int(os.getenv("ADX_THRESHOLD", 25))
DATA_FILE = "best_ema_results.csv"

# =========================================================
# DISCORD ALERT (EMBED)
# =========================================================
def send_discord_alert_embed(ticker, price, fast, slow, adx, custom_text):
    if not DISCORD_WEBHOOK_URL:
        return

    color = 3066993 if adx >= 30 else 15105570  # Green / Yellow

    payload = {
        "username": "EMA Trend Scanner",
        "embeds": [{
            "title": f"{ticker} – BULLISH EMA CROSS 🚀",
            "color": color,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "EMA Setup", "value": f"{fast} / {slow}", "inline": True},
                {"name": "ADX", "value": f"{adx:.1f}", "inline": True},
                {"name": "Strategy Notes", "value": custom_text, "inline": False}
            ],
            "footer": {
                "text": f"Scanner • {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        }]
    }

    requests.post(DISCORD_WEBHOOK_URL, json=payload)

# =========================================================
# EMAIL ALERT
# =========================================================
def send_email_alert(subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Email error: {e}")

# =========================================================
# INDICATORS
# =========================================================
def calculate_indicators(df, fast, slow):
    df = df.copy()

    df["Fast_EMA"] = df["Close"].ewm(span=fast, adjust=False).mean()
    df["Slow_EMA"] = df["Close"].ewm(span=slow, adjust=False).mean()

    df["UpMove"] = df["High"] - df["High"].shift(1)
    df["DownMove"] = df["Low"].shift(1) - df["Low"]

    df["+DM"] = 0.0
    df["-DM"] = 0.0

    df.loc[(df["UpMove"] > df["DownMove"]) & (df["UpMove"] > 0), "+DM"] = df["UpMove"]
    df.loc[(df["DownMove"] > df["UpMove"]) & (df["DownMove"] > 0), "-DM"] = df["DownMove"]

    df["TR"] = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs()
    ], axis=1).max(axis=1)

    df["TR14"] = df["TR"].ewm(alpha=1/14, adjust=False).mean()
    df["+DI14"] = 100 * (df["+DM"].ewm(alpha=1/14).mean() / df["TR14"])
    df["-DI14"] = 100 * (df["-DM"].ewm(alpha=1/14).mean() / df["TR14"])
    df["DX"] = 100 * abs(df["+DI14"] - df["-DI14"]) / (df["+DI14"] + df["-DI14"])
    df["ADX"] = df["DX"].ewm(alpha=1/14).mean()

    return df

# =========================================================
# CUSTOM STRATEGY TEXT
# =========================================================
def build_custom_text(today, fast, slow):
    ema_gap = abs(today["Fast_EMA"] - today["Slow_EMA"]) / today["Close"] * 100

    if today["ADX"] >= 40:
        strength = "🔥 Very strong trend"
    elif today["ADX"] >= 30:
        strength = "💪 Strong trend"
    else:
        strength = "⚠️ Early trend"

    return (
        f"{strength}\n"
        f"Bullish EMA {fast}/{slow} crossover\n"
        f"EMA separation: {ema_gap:.2f}%"
    )

# =========================================================
# MAIN SCANNER
# =========================================================
def main():
    print("=== EMA + ADX Scanner Started ===")

    if not os.path.exists(DATA_FILE):
        print(f"Missing {DATA_FILE}")
        return

    ema_df = pd.read_csv(DATA_FILE)
    ema_df.columns = ema_df.columns.str.strip()

    daily_signals = []

    for _, row in ema_df.iterrows():
        ticker = row["Ticker"]
        fast = int(row["Fast"])
        slow = int(row["Slow"])

        try:
            data = yf.download(
                ticker,
                period="2y",
                interval="1d",
                progress=False,
                auto_adjust=False
            )

            if len(data) < slow + 5:
                continue

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            data = calculate_indicators(data, fast, slow)

            today = data.iloc[-1]
            yesterday = data.iloc[-2]

            bullish_cross = (
                yesterday["Fast_EMA"] <= yesterday["Slow_EMA"]
                and today["Fast_EMA"] > today["Slow_EMA"]
            )

            strong_trend = today["ADX"] >= ADX_THRESHOLD

            if bullish_cross and strong_trend:
                custom_text = build_custom_text(today, fast, slow)

                send_discord_alert_embed(
                    ticker=ticker,
                    price=today["Close"],
                    fast=fast,
                    slow=slow,
                    adx=today["ADX"],
                    custom_text=custom_text
                )

                daily_signals.append(
                    f"{ticker} | EMA {fast}/{slow} | ADX {today['ADX']:.1f}"
                )

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

    # =====================================================
    # DAILY EMAIL SUMMARY
    # =====================================================
    if daily_signals:
        report = (
            "DAILY EMA SCANNER REPORT\n\n"
            f"ADX Threshold: {ADX_THRESHOLD}\n"
            f"Signals Found: {len(daily_signals)}\n\n" +
            "\n".join(daily_signals)
        )

        send_email_alert(
            subject=f"EMA Scanner: {len(daily_signals)} Signals Found",
            body=report
        )

        print(report)
    else:
        print("No signals found today.")

# =========================================================
if __name__ == "__main__":
    main()
