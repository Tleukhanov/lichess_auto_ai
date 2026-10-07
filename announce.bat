@echo off
REM Опрос анонсов каждые 5 минут (турниры за час / за 10 мин / итоги).
powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://localhost:5000/cron/announce' -Method Post -TimeoutSec 60 | Out-Null } catch {}"
