@echo off
REM Ежедневное обновление аналитики федерации ( members + турниры + отчёт ).
REM Планировщик: schtasks /create /tn "ChessFedDaily" /tr "\"%~dp0daily.bat\"" /sc daily /st 00:00
cd /d "%~dp0"
set PY=C:\Users\huawei\AppData\Local\Programs\Python\Python314\python.exe
%PY% -m backend.db.members
%PY% -m backend.db.results
%PY% -m backend.db.weekly
