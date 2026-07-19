# Holiday Hub V2

A cohesive Flask travel app organised into Home, Journey, Explore, Family, Memories, Travel Wallet and Settings.

## Windows setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

## Email

Set `MAILTRAP_API_TOKEN` in `.env`. Never put a token in `app.py`, HTML or GitHub. Mailtrap production sending requires a verified sender domain. The demo sender can generally only send to the account owner's address.

Registration sends a styled verification email. Finalize Trip is owner-only and requires:

- verified registered email
- exact registered-email re-entry
- the phrase `FINALIZE`
- a confirmation checkbox
- a 15-minute cooldown

The destination is never taken from a form field; it is always `current_user.email`.

## Flight data

Set `AVIATIONSTACK_API_KEY`. Users enter only a flight number and date. The server requests status, airports, gate and terminal. If your provider plan uses a different endpoint or HTTPS policy, adjust `fetch_flight_data()`.

## Printing

`/trips/<id>/print` is a standalone HTML document and does not inherit the app layout. Uploaded image documents are each printed on a dedicated full page with the document title above the image.

## Database upgrades

This version has new models. For disposable local test data, delete `instance/holiday_hub.db` and restart. For real data, use Flask-Migrate/Alembic instead.
