@echo off
cd /d "%~dp0"
echo Installing dependencies...
py -m pip install -r requirements.txt
if errorlevel 1 (echo Could not install dependencies. Check Python installation. & pause & exit /b 1)
echo.
echo Make sure Ollama is running and the qwen3:8b model is installed.
echo Open http://127.0.0.1:5000 in your browser.
py app.py
pause
