# Streamlit demo deployment

The Streamlit demo is a separate presentation layer for free, link-based
testing. It imports the existing CricAtlas analytics and chat services. It does
not replace or modify the Next.js frontend.

## Local preview

Create the local environment once, then run the preview through that environment:

```bash
conda env create -f environment.local.yml
conda run --no-capture-output -n odi-analyst-workbench streamlit run streamlit_app.py
```

If `odi-analyst-workbench` is already active, `streamlit run streamlit_app.py`
is equivalent. `requirements.txt` remains the dependency source used by
Streamlit Community Cloud; it is not a second local runtime.

If the local DuckDB already exists, no download occurs.

## Test Ask Atlas ranking controls (#58)

Open `http://localhost:8501`, choose **Ask Atlas**, and start a **New analysis**.

1. Ask: **Who has the highest batting strike rate in powerplay against pace in 2023?**
   The result should show a default minimum of **60 balls faced**, a sort column,
   a direction, and **Apply** / **Reset** buttons.
2. Select **Matches**, enter **5**, and press **Apply**. Every displayed
   player must have at least five distinct ODIs within the original filters.
   The caption and answer should say five matches; the table and chart should
   contain the same players in the same order.
3. Select **Runs Scored** and **Ascending**, then apply. The lowest qualifying
   run total should appear first, the headline should name Runs Scored and say
   "lowest first", and the chart should plot Runs Scored. Switch to
   **Descending** and apply; the highest qualifying run total should now lead.
   This recalculates the full ranking before selecting the top rows.
4. Enter **1000000** and apply. Expect a clear no-qualifying-results error with
   no old answer, table, or chart. The error must survive unrelated reruns.
5. Press **Reset**. Expect the original result and controls, including
   60 balls faced and batting strike rate descending, with the error cleared.
   Entering **0** and applying explicitly removes the minimum.
6. Start a new analysis and ask: **Which bowler has the best death-over economy
   in 2023?** Repeat the sample and sort checks. Bowling must offer **Legal
   balls** and **Matches**; wides and no-balls do not count as legal balls.
7. Start a new analysis and ask: **Who has the highest strike rate in powerplay
   against pace in 2023?** Answer the metric clarification with **first**
   (batting). Apply a new minimum and sort. The original powerplay, pace, and
   2023 filters must remain in effect. A venue in the original question must
   also remain in effect.

Use the form's **Apply** button to change the full ranking. Clicking a
table header only sorts the rows already displayed. Reset restores the initial
answer's qualification and sort; an explicitly requested original threshold is
preserved as that answer's reset value.

Run the automated regression checks in the project environment:

```bash
conda run --no-capture-output -n odi-analyst-workbench python -m pytest tests/streamlit/test_issue_58_ranking_controls.py -q
```

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

## All-format records on the website

The website automatically downloads the prepared all-format records on its
first start. It reuses the file on later page changes and starts. If Streamlit
clears its stored files, the next start downloads them again. No manual file
copy or data setting is needed for the normal website.

The download is about 116 MiB compressed and becomes a 723 MiB DuckDB file.
`data/multiformat-download.json` records its fixed address, checksum and expected
file size. The app checks the download and opens it read-only before making
it available to chat and all four explorers. An unsuccessful download shows
a retry message instead of silently offering only ODIs.

Existing files are never overwritten or rebuilt. `MULTIFORMAT_DUCKDB_PATH`
can point to another prepared copy. The original ODI database remains in use
for the approved men's ODI pages while the two versions are checked separately.

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

The Streamlit app includes the shared database-backed chat plus Player,
Compare, Matchup, and Venue explorers for invited testing. The explorers use
the same repository and analytics services as the Docker/Next.js application.
