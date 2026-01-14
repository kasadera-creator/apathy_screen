# Import Secondary Auto-Extraction (Gemini) — Short Guide

This document lists the minimal, safe steps to import Gemini auto-extraction results into the application database.

- Run this on the server (do not commit data files to git).
- Default import mode is `insert-only` (will never overwrite existing records).

Steps

1) Ensure `DATABASE_URL` points to the target DB and show it in the environment:

```bash
export DATABASE_URL=sqlite:///./dev.db
echo $DATABASE_URL
```

2) Create tables if needed (this will import model classes and run `create_all`):

```bash
export AUTO_CREATE_TABLES=1
DATABASE_URL="$DATABASE_URL" python -m app.scripts.setup_db --create-tables
```

3) Run the import (default `insert-only`):

```bash
DATABASE_URL="$DATABASE_URL" python -m app.scripts.import_secondary_gemini_results --input data/extraction_results.csv
```

4) To upsert (overwrite) existing rows, use `--mode upsert --force` (use with caution):

```bash
DATABASE_URL="$DATABASE_URL" python -m app.scripts.import_secondary_gemini_results --input data/extraction_results.csv --mode upsert --force
```

5) To limit import to specific PMIDs:

```bash
DATABASE_URL="$DATABASE_URL" python -m app.scripts.import_secondary_gemini_results --input data/extraction_results.csv --pmid 12345,23456
```

Notes

- The import script will print the `DATABASE_URL` it uses before running.
- If the script detects the target table `secondaryautoextraction` is missing it will abort and show the `setup_db --create-tables` command to run.
- Do not commit `data/*.csv` or database files to git.
