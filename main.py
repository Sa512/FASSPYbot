"""
بوت تحليل SPY - يرسل تنبيهات فنية عبر تيليجرام
=================================================
تنويه مهم: هذا البوت يقدم إشارات فنية تعليمية مبنية على مؤشرات
تحليل فني وباك-تيست تاريخي. هذا ليس نصيحة استثمارية أو مالية،
والقرار والمسؤولية الكاملة على المستخدم.

المتطلبات (requirements.txt):
    yfinance, pandas, numpy, requests, apscheduler, pytz
"""

import os
import time
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# ============================ الإعدادات ============================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

SYMBOL = "SPY"
NY_TZ = pytz.timezone("America/New_York")

# إعدادات الاستراتيجية
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
STOP_LOSS_ATR_MULT = 1.5
TARGET_ATR_MULT = 2.5
MIN_MINUTES_BETWEEN_SIGNALS = 30  # تجنب إرسال إشارات متكررة متلاصقة

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("spy_bot")

_last_signal_time = None  # لتتبع آخر إشارة أُرسلت (لمنع التكرار)


# ============================ إرسال تيليجرام ============================
def send_telegram_message(text: str):
    """يرسل رسالة نصية إلى تيليجرام عبر Bot API مباشرة (بدون مكتبات إضافية)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code != 200:
            log.error(f"فشل إرسال الرسالة: {r.status_code} - {r.text}")
        else:
            log.info("تم إرسال الرسالة بنجاح.")
    except Exception as e:
        log.error(f"خطأ أثناء الإرسال إلى تيليجرام: {e}")


# ============================ جلب البيانات ============================
def get_intraday_data(period="5d", interval="5m") -> pd.DataFrame:
    """يجلب بيانات شموع 5 دقائق لآخر 5 أيام تداول."""
    df = yf.download(SYMBOL, period=period, interval=interval, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return df


def get_daily_data(period="6mo") -> pd.DataFrame:
    df = yf.download(SYMBOL, period=period, interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


# ============================ المؤشرات الفنية ============================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA_fast"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA_slow"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["RSI"] = df["RSI"].fillna(50)

    # MACD
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # ATR
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()

    return df


# ============================ منطق الإشارة ============================
def check_signal_at(df: pd.DataFrame, i: int):
    """
    يفحص إشارة عند الصف i بناءً على تقاطع EMA + تأكيد RSI و MACD.
    يرجع 'BUY' أو 'SELL' أو None
    """
    if i < 1:
        return None
    prev, cur = df.iloc[i - 1], df.iloc[i]

    crossed_up = prev["EMA_fast"] <= prev["EMA_slow"] and cur["EMA_fast"] > cur["EMA_slow"]
    crossed_down = prev["EMA_fast"] >= prev["EMA_slow"] and cur["EMA_fast"] < cur["EMA_slow"]

    if crossed_up and cur["RSI"] > 50 and cur["MACD"] > cur["MACD_signal"]:
        return "BUY"
    if crossed_down and cur["RSI"] < 50 and cur["MACD"] < cur["MACD_signal"]:
        return "SELL"
    return None


def generate_live_signal(df: pd.DataFrame):
    """يفحص آخر شمعة مكتملة لإشارة جديدة."""
    df = compute_indicators(df)
    last_i = len(df) - 1
    signal = check_signal_at(df, last_i)
    if signal is None:
        return None

    price = df["Close"].iloc[last_i]
    atr = df["ATR"].iloc[last_i]

    if signal == "BUY":
        stop_loss = price - STOP_LOSS_ATR_MULT * atr
        target = price + TARGET_ATR_MULT * atr
    else:
        stop_loss = price + STOP_LOSS_ATR_MULT * atr
        target = price - TARGET_ATR_MULT * atr

    return {
        "type": signal,
        "price": round(float(price), 2),
        "target": round(float(target), 2),
        "stop_loss": round(float(stop_loss), 2),
        "time": df.index[last_i],
    }


# ============================ الباك-تيست (نسبة النجاح التاريخية) ============================
def backtest_strategy(df: pd.DataFrame, lookahead_bars=20) -> dict:
    """
    يحسب نسبة نجاح الاستراتيجية تاريخياً:
    لكل إشارة سابقة، يفحص هل السعر وصل الهدف قبل وقف الخسارة خلال
    عدد الشموع القادمة (lookahead_bars).
    """
    df = compute_indicators(df)
    wins, losses, total = 0, 0, 0

    for i in range(EMA_SLOW, len(df) - lookahead_bars):
        signal = check_signal_at(df, i)
        if signal is None:
            continue

        entry = df["Close"].iloc[i]
        atr = df["ATR"].iloc[i]
        if signal == "BUY":
            target = entry + TARGET_ATR_MULT * atr
            stop = entry - STOP_LOSS_ATR_MULT * atr
        else:
            target = entry - TARGET_ATR_MULT * atr
            stop = entry + STOP_LOSS_ATR_MULT * atr

        future = df.iloc[i + 1: i + 1 + lookahead_bars]
        hit_target = hit_stop = False
        for _, row in future.iterrows():
            if signal == "BUY":
                if row["High"] >= target:
                    hit_target = True
                    break
                if row["Low"] <= stop:
                    hit_stop = True
                    break
            else:
                if row["Low"] <= target:
                    hit_target = True
                    break
                if row["High"] >= stop:
                    hit_stop = True
                    break

        total += 1
        if hit_target:
            wins += 1
        elif hit_stop:
            losses += 1

    win_rate = (wins / total * 100) if total > 0 else 0
    return {"total_signals": total, "wins": wins, "losses": losses, "win_rate": round(win_rate, 1)}


# ============================ صياغة الرسائل ============================
DISCLAIMER = (
    "\n\n⚠️ <i>هذا تحليل فني تعليمي وليس نصيحة استثمارية ملزمة. "
    "التداول ينطوي على مخاطر، والقرار والمسؤولية الكاملة على المتداول.</i>"
)


def format_signal_message(signal: dict, backtest: dict) -> str:
    emoji = "🟢" if signal["type"] == "BUY" else "🔴"
    label = "شراء (Long)" if signal["type"] == "BUY" else "بيع (Short)"
    return (
        f"{emoji} <b>إشارة جديدة على {SYMBOL}</b>\n\n"
        f"النوع: <b>{label}</b>\n"
        f"سعر الدخول: <b>${signal['price']}</b>\n"
        f"🎯 الهدف: <b>${signal['target']}</b>\n"
        f"🛑 وقف الخسارة: <b>${signal['stop_loss']}</b>\n\n"
        f"📊 نسبة النجاح التاريخية للاستراتيجية (آخر {backtest['total_signals']} إشارة): "
        f"<b>{backtest['win_rate']}%</b>\n"
        f"(أرباح: {backtest['wins']} | خسائر: {backtest['losses']})"
        f"{DISCLAIMER}"
    )


def format_market_open_message(daily_df: pd.DataFrame) -> str:
    prev_close = daily_df["Close"].iloc[-2]
    last_close = daily_df["Close"].iloc[-1]
    change_pct = (last_close - prev_close) / prev_close * 100

    ema20 = daily_df["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    trend = "صاعد 📈" if last_close > ema20 else "هابط 📉"

    return (
        f"🔔 <b>افتتاح السوق - {SYMBOL}</b>\n"
        f"📅 {datetime.now(NY_TZ).strftime('%Y-%m-%d')}\n\n"
        f"آخر إغلاق: <b>${prev_close:.2f}</b>\n"
        f"التغيّر: <b>{change_pct:+.2f}%</b>\n"
        f"الاتجاه العام (يومي): <b>{trend}</b>\n\n"
        f"سيتم إرسال أي إشارة تداول جديدة فور تكوّنها خلال الجلسة."
        f"{DISCLAIMER}"
    )


def format_market_close_message(daily_df: pd.DataFrame) -> str:
    last_close = daily_df["Close"].iloc[-1]
    prev_close = daily_df["Close"].iloc[-2]
    change_pct = (last_close - prev_close) / prev_close * 100
    return (
        f"🔚 <b>إغلاق السوق - {SYMBOL}</b>\n"
        f"سعر الإغلاق: <b>${last_close:.2f}</b>\n"
        f"التغيّر اليومي: <b>{change_pct:+.2f}%</b>"
        f"{DISCLAIMER}"
    )


# ============================ المهام المجدولة ============================
def job_market_open():
    log.info("تنفيذ مهمة افتتاح السوق...")
    try:
        daily = get_daily_data()
        msg = format_market_open_message(daily)
        send_telegram_message(msg)
    except Exception as e:
        log.error(f"خطأ في مهمة الافتتاح: {e}")


def job_market_close():
    log.info("تنفيذ مهمة إغلاق السوق...")
    try:
        daily = get_daily_data()
        msg = format_market_close_message(daily)
        send_telegram_message(msg)
    except Exception as e:
        log.error(f"خطأ في مهمة الإغلاق: {e}")


def job_check_signals():
    global _last_signal_time
    now_ny = datetime.now(NY_TZ)
    # يعمل فقط خلال ساعات التداول (9:30 - 16:00 بتوقيت نيويورك) ومن الاثنين للجمعة
    if now_ny.weekday() >= 5:
        return
    market_open = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
    if not (market_open <= now_ny <= market_close):
        return

    try:
        intraday = get_intraday_data()
        signal = generate_live_signal(intraday)
        if signal is None:
            log.info("لا توجد إشارة جديدة حالياً.")
            return

        if _last_signal_time is not None and (now_ny - _last_signal_time) < timedelta(minutes=MIN_MINUTES_BETWEEN_SIGNALS):
            log.info("تم تجاهل الإشارة لتجنب التكرار السريع.")
            return

        backtest = backtest_strategy(intraday)
        msg = format_signal_message(signal, backtest)
        send_telegram_message(msg)
        _last_signal_time = now_ny
    except Exception as e:
        log.error(f"خطأ في فحص الإشارات: {e}")


# ============================ التشغيل الرئيسي ============================
def main():
    log.info("بدء تشغيل بوت SPY...")
    send_telegram_message(f"✅ بوت {SYMBOL} بدأ التشغيل وجاهز لإرسال التنبيهات.")

    scheduler = BlockingScheduler(timezone=NY_TZ)

    # رسالة افتتاح السوق الساعة 9:30 صباحاً بتوقيت نيويورك (أيام الأسبوع)
    scheduler.add_job(job_market_open, CronTrigger(day_of_week="mon-fri", hour=9, minute=30))

    # رسالة إغلاق السوق الساعة 4:00 عصراً بتوقيت نيويورك
    scheduler.add_job(job_market_close, CronTrigger(day_of_week="mon-fri", hour=16, minute=0))

    # فحص الإشارات كل 5 دقائق (المهمة نفسها تتحقق من ساعات التداول)
    scheduler.add_job(job_check_signals, "interval", minutes=5)

    log.info("الجدولة جاهزة. البوت يعمل الآن بشكل مستمر (24 ساعة)...")
    scheduler.start()


if __name__ == "__main__":
    main()
