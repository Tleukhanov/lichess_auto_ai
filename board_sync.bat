@echo off
REM Автоснимок базы для борда: коммит + пуш federation.db, Heroku подхватывает сам.
cd /d "%~dp0"
set PY=C:\Users\huawei\AppData\Local\Programs\Python\Python314\python.exe
%PY% -m backend.db.results > "%TEMP%\board_sync.log" 2>&1
git add -f backend\db\federation.db > NUL 2>&1
git diff --cached --quiet
if %errorlevel%==0 exit /b 0
git -c user.name=Tleukhanov -c user.email=tleukhanov0409@mail.ru commit -m "chore: board snapshot %date% %time%" > NUL 2>&1
git push origin HEAD:main > NUL 2>&1
