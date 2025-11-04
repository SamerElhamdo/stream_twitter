# تثبيت الخدمة في Ubuntu / Service Installation Guide

دليل تثبيت وتشغيل Stream Server كخدمة systemd في Ubuntu.

## المتطلبات / Prerequisites

```bash
# تحديث النظام
sudo apt update

# تثبيت Python و pip
sudo apt install -y python3 python3-pip python3-venv

# تثبيت FFmpeg
sudo apt install -y ffmpeg

# تثبيت Gunicorn (سيتم تثبيته تلقائياً في السكريبت)
```

## طريقة 1: التثبيت التلقائي (مُوصى به)

```bash
# جعل سكريبت التثبيت قابلاً للتنفيذ
chmod +x install-service.sh

# تشغيل سكريبت التثبيت
sudo ./install-service.sh
```

## طريقة 2: التثبيت اليدوي

### 1. إنشاء مجلد التثبيت

```bash
sudo mkdir -p /root/stream_twitter
sudo mkdir -p /var/log/stream-server
sudo mkdir -p /var/streamctl/{pids,logs}
sudo mkdir -p /root/stream_twitter/uploads
```

### 2. نسخ الملفات

```bash
sudo cp -r . /root/stream_twitter/
sudo chown -R root:root /root/stream_twitter
sudo chown -R root:root /var/log/stream-server
sudo chown -R root:root /var/streamctl
```

### 3. إنشاء بيئة Python افتراضية

```bash
cd /root/stream_twitter
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
venv/bin/pip install gunicorn
```

### 4. تكوين ملف الخدمة

عدّل ملف `stream-server.service` وغيِّر:
- المسارات إذا كان مجلد التثبيت مختلف
- `WEBHOOK_TOKEN` في Environment variables
- أي متغيرات بيئة أخرى تحتاجها

### 5. تثبيت الخدمة

```bash
sudo cp stream-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable stream-server
sudo systemctl start stream-server
```

## إدارة الخدمة / Service Management

### بدء الخدمة
```bash
sudo systemctl start stream-server
```

### إيقاف الخدمة
```bash
sudo systemctl stop stream-server
```

### إعادة تشغيل الخدمة
```bash
sudo systemctl restart stream-server
```

### حالة الخدمة
```bash
sudo systemctl status stream-server
```

### عرض السجلات
```bash
# عرض السجلات في الوقت الفعلي
sudo journalctl -u stream-server -f

# عرض آخر 100 سطر
sudo journalctl -u stream-server -n 100

# عرض السجلات من اليوم
sudo journalctl -u stream-server --since today
```

### عرض سجلات Gunicorn
```bash
# Access log
sudo tail -f /var/log/stream-server/access.log

# Error log
sudo tail -f /var/log/stream-server/error.log
```

## إعدادات مهمة / Important Configuration

### 1. ملف .env

أنشئ ملف `.env` في `/root/stream_twitter/`:

```env
PORT=3000
WEBHOOK_TOKEN=your_secret_token_here
STREAM_CTL_DIR=/var/streamctl
FFMPEG_BIN=/usr/bin/ffmpeg
OVERLAY_IMAGE=overlay_straem.png
```

### 2. تحديث متغيرات البيئة في ملف الخدمة

عدّل `/etc/systemd/system/stream-server.service`:

```ini
Environment="WEBHOOK_TOKEN=your_actual_token"
Environment="PORT=3000"
```

ثم أعد تحميل وتشغيل الخدمة:

```bash
sudo systemctl daemon-reload
sudo systemctl restart stream-server
```

## استكشاف الأخطاء / Troubleshooting

### الخدمة لا تبدأ

```bash
# فحص حالة الخدمة
sudo systemctl status stream-server

# فحص السجلات للأخطاء
sudo journalctl -u stream-server -n 50

# فحص الأذونات
ls -la /root/stream_twitter
ls -la /var/streamctl
```

### مشاكل الأذونات

```bash
sudo chown -R root:root /root/stream_twitter
sudo chown -R root:root /var/streamctl
sudo chown -R root:root /var/log/stream-server
```

### تغيير المنفذ

إذا كنت تريد استخدام منفذ غير 3000:

1. عدّل `.env`:
   ```env
   PORT=8080
   ```

2. عدّل `stream-server.service`:
   ```ini
   Environment="PORT=8080"
   ExecStart=... --bind 0.0.0.0:8080 ...
   ```

3. أعد تحميل الخدمة:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart stream-server
   ```

## إزالة الخدمة / Uninstall

```bash
# إيقاف وتعطيل الخدمة
sudo systemctl stop stream-server
sudo systemctl disable stream-server

# حذف ملف الخدمة
sudo rm /etc/systemd/system/stream-server.service

# إعادة تحميل systemd
sudo systemctl daemon-reload

# (اختياري) حذف الملفات (احذر: هذا سيحذف كل شيء!)
# sudo rm -rf /root/stream_twitter
# sudo rm -rf /var/streamctl
# sudo rm -rf /var/log/stream-server
```

## ملاحظات أمنية / Security Notes

1. **غير WEBHOOK_TOKEN** في ملف `.env` أو في service file
2. استخدم **firewall** للتحكم في الوصول للمنفذ
3. فكّر في استخدام **reverse proxy** (nginx) مع SSL
4. راجع أذونات الملفات والمجلدات بانتظام

## مثال إعداد Nginx كـ Reverse Proxy

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
