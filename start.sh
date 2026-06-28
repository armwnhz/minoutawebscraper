#!/bin/bash

# اجرای مهاجرت دیتابیس (اگر نیاز باشد)
# python manage.py migrate

# شروع برنامه
gunicorn -w 4 -k uvicorn.workers.UvicornWorker minouta:app