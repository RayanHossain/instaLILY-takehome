# Project
An AI sales-intelligence tool for a roofing distributor. A batch pipeline finds GAF-certified roofing contractors near a branch, enriches them, scores them, and writes briefs; a Streamlit app shows reps a ranked lead list. README.md covers running and customizing it; DESIGN.md covers how it's designed and why.

# Stack
Python 3.11+, SQLAlchemy 2.0 (typed ORM models), Alembic (render_as_batch=True), Pydantic v2 with pydantic-settings, httpx, PyYAML, beautifulsoup4 (GAF profile pages), pytest, argparse for the CLI, Streamlit (the rep UI), google-genai (the Gemini API SDK, used only in app/ai). Versions are pinned in requirements.txt.

# Rules
- SQLite at data/leads.db via DATABASE_URL; data/ is gitignored. seed/leads.db is the committed starting copy. Stay portable to Postgres: SQLAlchemy types only, no raw SQLite SQL.
- New rows go through the upsert helper; enrichment stages update existing rows by primary key with SQLAlchemy's update().
- Every schema change is a new Alembic migration.
- Secrets live in .env only, never in code, tests, fixtures, the seed, or logs. API keys are optional in Settings: the stage that needs one stops with a message naming it.
- Every raw response is saved before it's parsed.
- Pipeline stages are separate functions: each is safe to rerun, skips finished work, and never calls another stage.
- The pipeline writes generated data only. Reps' notes and statuses are written only through the service layer, and the pipeline never writes them.
- AI calls go through app/ai only. The AI never computes scores.
- Services take a database session as an argument and return Pydantic models. The Streamlit UI calls them only through app/ui/data.py.
- The Streamlit skill guides presentation only. Where it conflicts with these rules, these rules win: the UI gets data only through app/ui/data.py, never st.connection or its own queries, and uses only Streamlit features available in the pinned version.
- Tests never touch the network; they use saved fixtures in tests/fixtures/.
- Never delete or overwrite data/leads.db. Tests use temporary databases, and review agents work on a copy. It runs in WAL mode, so copy it with SQLite's backup API, never a plain cp, which can miss writes still in the WAL file.

# Layout
- config/: distributor.yaml (territory and selling points), scoring.yaml (every scoring number, rules_version, and the presets)
- app/settings.py: reads .env (Settings) and config/distributor.yaml (load_territory, load_selling_points)
- app/scoring.py: loads config/scoring.yaml and applies it (pure rule functions; total() combines components with a preset)
- app/briefs.py: the Brief output model, the selling-point rules, and check_brief()
- app/db/: engine (make_engine, the one place SQLite settings live), models, upsert helper. No session module: callers open sqlalchemy.orm.Session(engine) directly. The UI's cached engine and session helper live in app/ui/data.py.
- app/sources/: one adapter per data source (coveo.py for GAF's search, gaf_profile.py, websites.py)
- app/pipeline/: CLI entry point and one module per stage
- app/services/: one module per area (leads.py, notes.py, reps.py); functions take a session and return Pydantic models
- app/ui/: main.py and data.py (the UI's only route to services). main() draws what both pages share (sidebar, title, preset picker), then runs the current page through st.navigation: top_leads_page() (Top leads, the landing page) or all_leads_page() (All leads). streamlit_app.py at the repo root calls main().
- app_pages/: top_leads.py and all_leads.py, two-line files that call the page functions in app/ui/main.py. st.navigation needs a file per page so AppTest can switch to it.
- app/ai/: client.py (generate(), the one way to call the AI: ai_cache, validation, pacing, backoff) and prompts/ (versioned prompt files, e.g. extract_facts_v1.txt; a stage names its prompt in PROMPT)
- app/evals/: python -m app.evals extract scores each extracted field's precision and recall against evals/extract_gold.yaml (hand-corrected gold), from cached answers, and writes each gold contractor's exact input to evals/inputs/<GAF ID>.txt (gitignored)
- migrations/: Alembic. The initial migration also seeds the demo rep (10013, 25 miles).
- seed/: leads.db, the pipeline's output for ZIP 10013 without the raw GAF pages (only the 10 homepages the eval needs), with no rep notes
- docs/: the README's screenshots
- tests/, tests/fixtures/

# Commands
Run everything from the repo root: .env and data/leads.db are found relative to the current directory.
- Set up: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && cp .env.example .env && mkdir -p data && cp seed/leads.db data/leads.db`. No keys are needed to run the app, the tests, the score stage, or the eval on the seed. Discover needs COVEO_API_KEY; extract and brief need GEMINI_API_KEY.
- Build the database: `alembic upgrade head`
- Run tests: `pytest`
- Run the pipeline: `python -m app.pipeline run --stages discover,fetch,parse,check_websites,capture_websites,extract,score,brief` (comma-separated, run in order; any subset works). `python -m app.pipeline stats` prints the latest AI stage run's numbers. The seed has no raw GAF pages, so on it run only score; anything else starts again from discover.
- Run the extraction eval: `python -m app.evals extract` (calls the AI only on a cache miss)
- Run the app: `streamlit run streamlit_app.py` (opens http://localhost:8501). After editing code under app/, click Rerun in the open tab; reloading the tab keeps the old code until the server restarts.
