# copilot-in-telegram

把 Copilot CLI 体验搬到 Telegram

初步版本，目前仅实现了部分交互功能

## 快速启动

```powershell
pip install -e .
Copy-Item .env.example .env
copilot login
python -m copilot_in_telegram.main
```

如果访问 Telegram 需要代理，设置 `TELEGRAM_PROXY_URL`
