# Schedule to Calendar

A local web app for turning a monthly teacher schedule screenshot into calendar events.

## Use

1. Run `python3 server.py`.
2. Open `http://localhost:4173`.
3. Upload one or more schedule screenshots.
   - Use non-overlapping screenshots so each date row appears only once.
4. Click **Scan with OpenRouter**.
5. Review or fix the recognized text and event rows.
6. Click **Parse Events** if you edited the text.
7. Click **Download ICS** or **Download for Apple**.

## OpenRouter Setup

Create or edit the `.env` file in this folder, next to `server.py`:

```text
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=openrouter/auto
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
```

Then restart `python3 server.py`.

If you want a starting template, copy `.env.example` to `.env` and paste your Groq key into `GROQ_API_KEY=...`.

The OpenRouter button uses the local `server.py` backend so your API key stays out of the browser. If OpenRouter hits a rate limit, Groq is used automatically as a fallback when its key is configured.

The exported `.ics` follows the same simple style as the provided example:

- `PRODID:-//EscondeKervin Schedule//EN`
- `X-WR-CALNAME` from the calendar name field
- timed events use `DTSTART:YYYYMMDDTHHMMSS`
- day-off rows export as all-day `VALUE=DATE` events

## Calendar Import

- **Apple Calendar:** open the downloaded `.ics` file.
- **Google Calendar:** click **Download for Google**, then go to Google Calendar settings, choose **Import & export**, and import the `.ics` file.

Bulk automatic Google Calendar insertion requires Google OAuth credentials. The `.ics` workflow avoids that setup and works for both Apple Calendar and Google Calendar.

## Share Online With Render

This project is ready to deploy on Render as a Python web service.

1. Push this folder to a GitHub repo.
2. In Render, create a new Web Service from that repo.
3. Use these settings:
   - Runtime: `Python`
   - Build command: `true`
   - Start command: `python3 server.py`
4. Add these environment variables in Render:
   - `OPENROUTER_API_KEY`
   - `GROQ_API_KEY`
   - `OPENROUTER_MODEL=openrouter/auto`
   - `GROQ_MODEL=meta-llama/llama-4-scout-17b-16e-instruct`

The included `render.yaml` contains the same settings for Render Blueprint deploys.

After deployment, future updates are:

1. Edit the files locally.
2. Test on `http://localhost:4173`.
3. Commit and push to GitHub.
4. Render redeploys from Git.

Keep `.env` local only. Use Render environment variables for production API keys.
