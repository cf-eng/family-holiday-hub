# Family Holiday Hub — Cinematic Edition

## Run
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

Important: this edition has expanded database models. If upgrading an earlier test copy, delete `instance/holiday_hub.db` once so Flask creates the new schema. Do not do this if you need to preserve existing data; migrate it instead.

## Print quality
The itinerary and overview print routes are standalone documents and do not extend `base.html`. In Chrome/Edge print settings enable **Background graphics**, choose the page size requested by the document, and set margins to Default or None.
