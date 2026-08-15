# Streamlit demo deployment

The Streamlit demo is a separate presentation layer for free, link-based
testing. It imports the existing CricAtlas analytics and chat services. It does
not replace or modify the Next.js frontend.

## Local preview

Install the Python requirements and run:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

If the local DuckDB already exists, no download occurs.

## Streamlit Community Cloud

1. Push the repository to GitHub.
2. In Streamlit Community Cloud, create an app from the repository.
3. Set the entrypoint to `streamlit_app.py`.
4. Choose a public subdomain such as `cricatlas.streamlit.app` if available.
5. Add the contents of `.streamlit/secrets.toml.example` in the app's Secrets
   panel, replacing placeholders with the verified data URL and new Gemini key.
6. Deploy and wait for the first data bootstrap to finish.

The initial start can take several minutes because the server may need to
download the source CSV and build DuckDB. Later starts reuse the generated file
when the platform retains it; the bootstrap safely repeats after a clean
rebuild or storage reset.

## Secrets

Never commit `.streamlit/secrets.toml`. Store these only in Streamlit's Secrets
panel:

- `GEMINI_API_KEY`
- `CRICATLAS_DATA_URL`
- `CRICATLAS_DATA_SHA256`
- `CRICATLAS_DATA_ARCHIVE_MEMBER`

The demo can run without Gemini, but interpretation and narrative quality will
be reduced. Use a dedicated Gemini project with the intended spending cap.

## Product boundary

The Docker/Next.js application remains the full CricAtlas experience. The
Streamlit app intentionally focuses on chat, tables, Plotly charts, evidence,
metric definitions and limitations for invited testing.
