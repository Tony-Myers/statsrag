# statsrag (Docker, offline-first)

A small local app to:
1) choose philosophical + probability framework profiles,
2) create an audit-ready analysis specification (no LLM required),
3) index your local sources (PDF/MD/TXT),
4) generate a structured prompt for a downstream LLM (e.g., Julius, a commercial LLM, or a local model),
5) upload the resulting artefacts + interpretation,
6) generate a verification report (RAG-assisted) to flag potential errors/overclaims.

## Key design choices
- **No prefilled variables/models** by default.
- **Dataset-driven variable selection**: upload CSV/XLSX/XLS, then pick outcome/predictors from detected columns.
- **Framework-aware metrics**: Bayesian mode offers PSIS-LOO / WAIC options; frequentist mode offers AIC/BIC and CV RMSE/MAE/R².
- **Local sources stay local**: put PDFs/notes under `./data/sources/` on your machine. The repo ignores `data/` so you do not accidentally commit copyrighted material.

## Installation options
There are two supported ways to run statsrag:

- **Recommended (pre-built image)**: download the **distribution ZIP** from GitHub Releases and run it. This pulls a pre-built container image (no local build step).
- **From source (build locally)**: clone the repository and build the container locally.

If you are unsure, use the **pre-built image** method.

---

## Quick start (distribution ZIP, recommended)

### macOS
1. Install Docker Desktop and make sure it is running.
2. Download the distribution ZIP from GitHub Releases and unzip it.
3. Either:
   - Double-click `start-statsrag.command` (if included), **or**
   - Open Terminal in the unzipped folder and run:

```bash
docker compose up
```

4. Open: http://localhost:8501

Stop with Ctrl+C, then run:

```bash
docker compose down
```

If macOS blocks the `.command` file: right-click → **Open** → **Open**.

### Windows
1. Install Docker Desktop (WSL2 enabled) and make sure it is running.
2. Download the distribution ZIP from GitHub Releases and unzip it.
3. Either:
   - Double-click `start-statsrag.bat` (if included), **or**
   - Open PowerShell in the unzipped folder and run:

```powershell
docker compose up
```

4. Open: http://localhost:8501

To stop, close the window (or press Ctrl+C), then run:

```powershell
docker compose down
```

> Note: The distribution ZIP pulls a pre-built image from GHCR (no local build step).

---

## Quick start (from source: build locally)

### macOS / Linux
1. Install Docker Desktop and make sure it is running.
2. Clone the repo and open a Terminal in the repo root.
3. Run:

```bash
docker compose up --build
```

4. Open: http://localhost:8501

Stop with Ctrl+C, then:

```bash
docker compose down
```

### Windows
1. Install Docker Desktop (WSL2 enabled) and make sure it is running.
2. Open PowerShell in the repo root and run:

```powershell
docker compose up --build
```

3. Open: http://localhost:8501

---

## Where to put your sources (stay local)
Put sources in:

`./data/sources/` (on your machine)

You may organise them into subfolders, for example:

- `./data/sources/interpretation_guardrails/`
- `./data/sources/modelling_practice/`
- `./data/sources/reporting_standards/`

Then in the app, go to **Sources → build/refresh index**.

## Notes on copyrighted PDFs and privacy
This project does not ship any PDFs. Your sources remain local under `data/sources/` and are not uploaded anywhere by the app. The repository includes `.gitignore` rules so `data/` is not tracked by Git.

## Troubleshooting (common)
- **Port 8501 already in use**: stop other containers using the port, or change the port mapping in `docker-compose.yml`.
- **Docker not available on managed machines**: some university/enterprise devices block Docker Desktop. In that case, you can follow along using screenshots or a hosted demo (if provided).

---

## Optional: one-click launchers included in the distribution ZIP

If your distribution ZIP includes launcher scripts, they should be named exactly as below.

### macOS launcher: `start-statsrag.command`

Create a file called `start-statsrag.command` in the same folder as `docker-compose.yml`:

```bash
#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Starting statsrag..."
echo "When the app is running, open: http://localhost:8501"
echo ""
echo "Stopping: press Ctrl+C, then run: docker compose down"
echo ""

docker compose up
```

Make it executable **before** you zip the distribution folder:

```bash
chmod +x start-statsrag.command
```

### Windows launcher: `start-statsrag.bat`

Create a file called `start-statsrag.bat` in the same folder as `docker-compose.yml`:

```bat
@echo off
setlocal

cd /d "%~dp0"

echo Starting statsrag...
echo When the app is running, open: http://localhost:8501
echo.
echo Stopping: close this window, then run: docker compose down
echo.

docker compose up

endlocal
```

---

GHCR image (example): `ghcr.io/tony-myers/statsrag:0.3.15`  
Version: v3
