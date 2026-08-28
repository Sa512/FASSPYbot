# بوت تحليل SPY عبر تيليجرام

بوت يراقب سهم/صندوق SPY أثناء ساعات تداول السوق الأمريكي ويرسل:
- رسالة عند **افتتاح السوق** (9:30 صباحاً بتوقيت نيويورك) بملخص الاتجاه العام
- **إشارات تداول** فورية (شراء/بيع) مع سعر الدخول، الهدف، وقف الخسارة، ونسبة النجاح التاريخية
- رسالة عند **إغلاق السوق** (4:00 عصراً بتوقيت نيويورك)

> ⚠️ **تنويه:** هذا أداة تحليل فني تعليمية مبنية على قواعد ومؤشرات (EMA, RSI, MACD, ATR)
> وباك-تيست تاريخي. هذا **ليس نصيحة استثمارية**، ولا يضمن أي ربح. التداول فيه مخاطرة
> والقرار النهائي والمسؤولية الكاملة على المستخدم.

---

## الخطوة 1: إنشاء بوت تيليجرام

1. افتح تيليجرام وابحث عن `@BotFather`
2. أرسل له `/newbot` واتبع التعليمات (اسم البوت + username ينتهي بـ bot)
3. راح يعطيك **Token** شكله تقريباً: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`
4. احفظه — هذا هو `TELEGRAM_BOT_TOKEN`

## الخطوة 2: الحصول على Chat ID

1. ابدأ محادثة مع البوت اللي أنشأته (اضغط Start)
2. أرسل له أي رسالة (مثلاً "hi")
3. افتح هذا الرابط في المتصفح (بدّل `<TOKEN>` بتوكنك):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. راح تشوف رقم داخل `"chat":{"id": XXXXXXXXX}` — هذا هو `TELEGRAM_CHAT_ID`

## الخطوة 3: التشغيل المحلي (للتجربة)

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="ضع_التوكن_هنا"
export TELEGRAM_CHAT_ID="ضع_الشات_آيدي_هنا"

python main.py
```

إذا كل شي تمام، بتوصلك رسالة "✅ بوت SPY بدأ التشغيل" على تيليجرام فوراً.

---

## الخطوة 4: التشغيل 24 ساعة (الاستضافة)

### الخيار الأسهل: Railway.app

1. ارفع مجلد المشروع (main.py, requirements.txt, Procfile) إلى مستودع GitHub جديد
2. سجّل دخول في [railway.app](https://railway.app) بحساب GitHub
3. اضغط **New Project → Deploy from GitHub repo** واختر المستودع
4. من تبويب **Variables** ضيف:
   - `TELEGRAM_BOT_TOKEN` = التوكن
   - `TELEGRAM_CHAT_ID` = الشات آيدي
5. Railway بيتعرف على `Procfile` تلقائياً ويشغّل البوت كـ worker مستمر 24 ساعة
6. من تبويب **Deployments** تقدر تتابع الـ logs وتتأكد إنه شغال

### بديل: Render.com

نفس الخطوات تقريباً، بس تختار **Background Worker** بدل Web Service عند الإنشاء،
وتحط نفس المتغيرات (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

### بديل: VPS خاص (DigitalOcean / Vultr / أي سيرفر لينكس)

```bash
# على السيرفر
git clone <رابط_مستودعك>
cd spy_bot
pip install -r requirements.txt

# تشغيل دائم باستخدام systemd (موصى به)
sudo nano /etc/systemd/system/spybot.service
```

محتوى ملف الخدمة:
```ini
[Unit]
Description=SPY Telegram Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /root/spy_bot/main.py
WorkingDirectory=/root/spy_bot
Environment="TELEGRAM_BOT_TOKEN=ضع_التوكن"
Environment="TELEGRAM_CHAT_ID=ضع_الشات_آيدي"
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable spybot
sudo systemctl start spybot
sudo systemctl status spybot   # للتأكد إنه شغال
```

---

## كيف تشتغل الاستراتيجية بالتفصيل

1. **جلب بيانات:** شموع 5 دقائق من Yahoo Finance لآخر 5 أيام تداول
2. **المؤشرات:**
   - `EMA9` و `EMA21` لتحديد الاتجاه القصير
   - `RSI(14)` لتأكيد قوة الحركة
   - `MACD` لتأكيد إضافي على الزخم
   - `ATR(14)` لحساب حجم التذبذب (يُستخدم لتحديد الهدف ووقف الخسارة ديناميكياً)
3. **شرط الشراء:** تقاطع EMA9 فوق EMA21 + RSI > 50 + MACD فوق خط الإشارة
4. **شرط البيع:** تقاطع EMA9 تحت EMA21 + RSI < 50 + MACD تحت خط الإشارة
5. **الهدف / وقف الخسارة:** يُحسب بالنسبة لـ ATR (تذبذب حقيقي)، مو رقم ثابت — يتكيف مع حالة السوق
6. **نسبة النجاح:** الكود يرجع بالتاريخ ويفحص كل الإشارات السابقة، ويحسب كم منها وصل
   للهدف قبل وقف الخسارة خلال أول 20 شمعة — هذا رقم **تاريخي حقيقي**، مو تقديري

## تعديل الإعدادات

في أعلى ملف `main.py` تقدر تعدّل:
- `EMA_FAST`, `EMA_SLOW` — حساسية تقاطع المتوسطات
- `STOP_LOSS_ATR_MULT`, `TARGET_ATR_MULT` — نسبة المخاطرة للعائد
- المهام المجدولة (أوقات الافتتاح/الإغلاق، وتكرار فحص الإشارات كل 5 دقائق)

## قيود مهمة

- بيانات Yahoo Finance المجانية قد تتأخر بضع ثوانٍ إلى دقائق — للتداول عالي التردد
  تحتاج مصدر بيانات مدفوع مباشر (مثل Alpaca أو Polygon.io)
- الباك-تيست يعتمد على بيانات 5 أيام فقط بسبب قيود يفاينانس على بيانات 5 دقائق —
  كلما زادت الفترة، زادت دقة نسبة النجاح
