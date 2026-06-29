# Bingo18 Predictor

Hệ thống ML dự đoán kết quả xổ số Bingo18 với real-time learning.

## Platform

- **Windows 11** with Python 3.11
- Terminal: CMD or PowerShell (NOT bash/Linux syntax)
- **Avoid `&` for background processes** — use `start /b python app.py` instead
- **Avoid `taskkill /F /IM python.exe`** — kills sync_to_supabase.py watcher too.
  Find specific PID first: `netstat -ano | findstr :8080`, then `taskkill /F /PID <PID>`

## Architecture

- Database: Supabase PostgreSQL (~64k draws, 30k+ predictions)
- Backend: Flask Python 3.11 on Google Cloud Run (region asia-southeast1)
- Scheduler: 3 Cloud Scheduler jobs (predict every 6min, sync-github daily, daily-summary 23:55)
- Real-time sync: Local script `sync_to_supabase.py --mode watch` (Vietlott blocks Cloud Run IPs, so must run on user PC)
- Notifications: Telegram bot
- Dashboard: `templates/dashboard.html` served at `/`

## Key files

- `app.py` - Flask app, 15+ API endpoints. **MUST import `pandas as pd` at top**
- `prediction_service.py` - Prediction orchestration + online learning
- `models.py` - Markov, ColdNumber, MLEnsemble, Hybrid, ModelSelector
- `lstm_model.py` - LSTM models (`BingoPredictor` binary + `FullLSTMPredictor` 56-class); trained locally only — TF disabled on Cloud Run (not in requirements.txt). Confirmed no predictive signal: val_loss ≈ 4.026 (random chance), mode collapse to single combo. Keep FWBR.
- `train_lstm_full.py` - FullLSTM 56-class retrainer + FWBR backtest (local only, ~64k draws)
- `ai_predictor.py` - OpenRouter/Groq/Gemini LLM integration
- `database.py` - PostgreSQL + SQLite abstraction
- `sync_to_supabase.py` - Local watcher (reads DB_HOST/DB_USER/DB_PASSWORD from .env)
- `sync_predictions.py` - Backfill predictions for missing draws
- `admin_interface.py` - Admin endpoints

## Testing locally on Windows

```
REM Kill stale server first:
netstat -ano | findstr :8080
taskkill /F /PID <PID>

REM Run in foreground:
python app.py

REM In another CMD:
curl http://localhost:8080/api/health
```

## Deployment

Two-step (avoids ContainerImageImportFailed with --source):
```
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/bingo18-predictor/bingo18-images/bingo18:TAG --project bingo18-predictor
gcloud run deploy bingo18 --image asia-southeast1-docker.pkg.dev/bingo18-predictor/bingo18-images/bingo18:TAG --region asia-southeast1 --project bingo18-predictor
```

Service URL: https://bingo18-633959711537.asia-southeast1.run.app

## Conventions

- Timestamps stored as UTC TIMESTAMP (not timestamptz)
- For VN date queries: `AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Ho_Chi_Minh'`
- Bingo18 numbers are 1-6, 3 numbers per draw, CAN repeat
- Size categories: NHO (sum 3-9), HOA (10-11), LON (12-18)
- Win definition: predicted SIZE == actual SIZE = WIN (baseline ~35%)
- match_count = số số trùng (thông tin phụ, không dùng tính thắng/thua)

## Env vars

Cloud Run set via `gcloud run services update --update-env-vars`:
- DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- ADMIN_SECRET_KEY, TRIGGER_SECRET
- OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY

Local: `.env` file (load with python-dotenv — NOT auto-loaded).

## Don't

- Never commit `.env`, `data/*.db`, `*.log`
- Never hardcode credentials in code
- Never truncate `predictions` without handling `prediction_results` FK
- Never run `taskkill /F /IM python.exe` — kills the watcher too
