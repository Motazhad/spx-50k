# SPX 50K Dashboard

نسخة مجانية بسيطة للجوال تعرض سعر SPX، وعقود SPX 0DTE فقط، ولا يظهر العقد إلا إذا Volume >= 50,000.

## تشغيل محلي
pip install -r requirements.txt
python app.py

ثم افتح:
http://127.0.0.1:8000

## رفعه على Render / Railway
Build command:
pip install -r requirements.txt

Start command:
gunicorn app:app

## مهم
هذه النسخة تعتمد على بيانات Yahoo Finance عبر yfinance.
البيانات المجانية قد تكون متأخرة وليست OPRA Real-Time.
التحديث في الواجهة كل 60 ثانية لتقليل احتمالية حظر المصدر المجاني.
إذا لم يوجد expiration في نفس تاريخ نيويورك، لن يعرض Expiration آخر على أنه 0DTE.
