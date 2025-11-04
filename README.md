# Stream Control Server

خادم Flask لإدارة تدفقات FFmpeg بين مصادر HLS وأهداف RTMP.

A Flask server for managing FFmpeg streams between HLS sources and RTMP destinations.

## الميزات / Features

- ✅ بدء وإيقاف تدفقات FFmpeg
- ✅ عرض حالة التدفقات
- ✅ إدارة ملفات PID والسجلات
- ✅ دعم Overlay للصور
- ✅ واجهة ويب بسيطة للتحكم
- ✅ API RESTful كامل

## التثبيت / Installation

```bash
# تثبيت المتطلبات
pip install -r requirements.txt
```

## الإعداد / Configuration

أنشئ ملف `.env` في مجلد المشروع:

```env
PORT=3000
WEBHOOK_TOKEN=your_secret_token_here
STREAM_CTL_DIR=/var/streamctl
FFMPEG_BIN=/usr/bin/ffmpeg
```

## البنية / Structure

```
stream_twitter/
├── config.py          # الإعدادات والتكوين
├── stream_manager.py  # إدارة العمليات والتدفقات
├── routes.py          # مسارات Flask API
├── utils.py           # دوال مساعدة
├── main.py            # نقطة البداية الرئيسية
├── requirements.txt   # المتطلبات
└── README.md          # هذا الملف
```

## الاستخدام / Usage

### تشغيل الخادم / Start Server

```bash
python main.py
```

### API Endpoints

#### بدء تدفق / Start Stream
```bash
POST /start
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json

{
  "id": "stream1",
  "hls": "http://example.com/stream.m3u8",
  "rtmp": "rtmp://live.example.com/live/stream_key",
  "image": "/path/to/overlay.png",  # optional
  "extra_args": []  # optional
}
```

#### إيقاف تدفق / Stop Stream
```bash
POST /stop
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json

{
  "id": "stream1"
}
```

#### حالة التدفق / Stream Status
```bash
GET /status?id=stream1
Authorization: Bearer YOUR_TOKEN
```

#### قائمة التدفقات / List Streams
```bash
GET /list
Authorization: Bearer YOUR_TOKEN
```

#### عرض السجلات / View Logs
```bash
GET /logs?id=stream1&lines=200
Authorization: Bearer YOUR_TOKEN
```

#### تنظيف / Cleanup
```bash
POST /cleanup
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json

{
  "kill_all_ffmpeg": false  # optional
}
```

#### إيقاف الكل / Stop All
```bash
POST /stop-all
Authorization: Bearer YOUR_TOKEN
```

### الواجهة الويب / Web UI

افتح المتصفح على: `http://localhost:3000/`

## التحسينات المطبقة / Improvements Applied

1. ✅ فصل الكود إلى وحدات منفصلة
2. ✅ تحسين معالجة الأخطاء
3. ✅ إضافة Type Hints
4. ✅ توثيق الكود بالتعليقات
5. ✅ تحسين واجهة المستخدم
6. ✅ إدارة أفضل للعمليات والموارد
7. ✅ تنظيف الكود وتحسين الأداء
