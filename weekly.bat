@echo off
REM Еженедельный отчёт федерации: итоги недели, топы, активность. Понедельник 00:00.
cd /d "%~dp0"
set PY=C:\Users\huawei\AppData\Local\Programs\Python\Python314\python.exe
%PY% -m backend.db.weekly
