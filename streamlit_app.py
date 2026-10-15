"""Entry point for the rep UI. Run from the repo root: streamlit run streamlit_app.py

Streamlit puts this file's folder, the repo root, on sys.path, so "app" is the app
package. Streamlit reruns this file on every interaction, and main() redraws the page.
"""

from app.ui.main import main

main()
