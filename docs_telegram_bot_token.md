1. Chat với @BotFather trên Telegram
2. Ghi lệnh: /newbot
3. Đặt tên bot (ví dụ: Bingo18_Bot)
4. Đặt username (phải kết thúc bằng _bot, ví dụ: Bingo18_Predictor_Bot)
5. Sao chép token mới (dạng: 123456789:ABCDEfghijklmnop...)
6. Update Cloud Run:
   gcloud run services update bingo18 \
     --region asia-southeast1 \
     --update-env-vars TELEGRAM_BOT_TOKEN=<TOKEN_MỚI>