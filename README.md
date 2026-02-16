# statsrag (docker, offline-first)

A small local app to:
1) choose philosophical + probability framework profiles,
2) create an audit-ready analysis specification (no LLM required),
3) index your local sources (PDF/MD/TXT),
4) generate a structured prompt for a downstream LLM (e.g., Julius or a local model),
5) upload the resulting artefacts + interpretation,
6) generate a verification report (RAG-assisted) to flag potential errors/overclaims.

## Key design choices
- **No prefilled VO2 variables/models** by default.
- **Dataset-driven variable selection**: upload CSV/XLSX/XLS, then pick outcome/predictors from detected columns.
- **Framework-aware metrics**: Bayesian mode offers PSIS-LOO / WAIC options; frequentist mode offers AIC/BIC and CV RMSE/MAE/R².
- **Local sources stay local**: put PDFs/notes under `./data/sources/` on *your machine*. The repo ignores `data/` so you do not accidentally commit copyrighted material.

## Quick start (macOS / Linux)
1. Install Docker Desktop.
2. Unzip this repo somewhere (e.g., Desktop).
3. In Terminal:

```bash
cd /path/to/statsrag_docker_repo_v3
docker compose up --build
```

4. Open: http://127.0.0.1:8501

Stop with Ctrl+C, then:

```bash
docker compose down
```

## Windows
- Install Docker Desktop (WSL2 enabled).
- Open PowerShell in the repo folder and run:

```powershell
docker compose up --build
```

Open http://127.0.0.1:8501

## Where to put your sources
Put sources in:

`./data/sources/` (on your host machine)

You may organise them into subfolders, e.g.:

- `./data/sources/interpretation_guardrails/`
- `./data/sources/modelling_practice/`
- `./data/sources/reporting_standards/`

Then in the app, go to **Step 3) Sources → build/refresh index**.

## Notes on copyrighted PDFs
This repo includes `.gitignore` rules so `data/` is not tracked by Git. You can still store your purchased PDFs locally in `data/sources/` and index them, without publishing them.

---
Version: v3
