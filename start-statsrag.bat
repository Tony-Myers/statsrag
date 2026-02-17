@echo off
setlocal

cd /d "%~dp0"

echo Starting statsrag...
echo Open: http://localhost:8501
echo.
echo To stop: close this window (or press Ctrl+C), then run: docker compose down
echo.

docker compose up

endlocal
