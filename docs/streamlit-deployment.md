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
5. In **Advanced settings → Secrets**, add the new Gemini key. No data URL is
   needed for the standard ODI dataset.
6. Deploy and wait for the first data bootstrap to finish.

The initial start can take several minutes because the server may need to
download the source CSV and build DuckDB. Later starts reuse the generated file
when the platform retains it; the bootstrap safely repeats after a clean
rebuild or storage reset.

## Secrets

Never commit `.streamlit/secrets.toml`. Store the Gemini key only in
Streamlit's private Secrets panel:

- `GEMINI_API_KEY`

`CRICATLAS_DATA_URL`, `CRICATLAS_DATA_SHA256`, and
`CRICATLAS_DATA_ARCHIVE_MEMBER` are optional developer overrides. The normal
deployment uses the verified publisher URL built into the bootstrap script.

The demo can run without Gemini, but interpretation and narrative quality will
be reduced. Use a dedicated Gemini project with the intended spending cap.

## Product boundary

The Docker/Next.js application remains the full CricAtlas experience. The
Streamlit app includes chat, Player Explorer and direct batter-versus-bowler
Matchups with filters, summary metrics and a pitch map for invited testing.
