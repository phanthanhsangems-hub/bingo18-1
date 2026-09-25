FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs data model_store

ENV PORT=8080
EXPOSE 8080

# P222: threads 8 -> 24.
#
# gunicorn voi --threads dung worker gthread: MOI REQUEST GIU MOT THREAD den
# khi tra xong. /api/sse/draws la luong song lau, giu tron mot thread toi 240
# giay (_SSE_MAX_LIFETIME), va app cho toi _SSE_MAX_CLIENTS = 5 luong cung luc.
# Voi 8 thread thi 5 tab dashboard mo cung luc chiem 5/8, con 3 thread cho toan
# bo phan con lai. Them mot request vao /api/weight-optimizer (do thuc te qua
# 30 giay, chan doan #29 bao curl rc=28) la con 2. Do dung la canh "app khong
# chay": trang khong phan hoi trong khi moi phep kiem tuan tu van xanh.
#
# 24 thread thi 5 luong SSE chi con la 5/24. Thread SSE gan nhu chi ngu
# (time.sleep(6) giua hai vong) nen rat re; cai dat gia that su la KET NOI DB:
# app co y KHONG dung connection pool (database.py:161 — pool gay can kiet vi
# nhieu endpoint tung ro ri), nen moi request dong thoi la mot ket noi
# Postgres. 24 la muc con an toan duoi han muc cua Supabase.
#
# KHONG tang --workers: moi worker nhan them mot bo ket noi DB va mot ban sao
# cache trong process, dat hon nhieu so voi thread.
#
# Neu sau nay doi _SSE_MAX_CLIENTS, phai giu no NHO HON HAN so thread nay.
CMD exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --workers 1 \
    --threads 24 \
    --timeout 300 \
    --graceful-timeout 300 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    "app:create_app()"
