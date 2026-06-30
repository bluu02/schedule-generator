#!/usr/bin/env python3
import base64
import io
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_default_policy
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
except ImportError:
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None
    ImageStat = None


PORT = int(os.environ.get("PORT", "4173"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/auto")
GROQ_URL = "https://api.groq.com/openai/v1/responses"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENROUTER_DOUBLE_CHECK = os.environ.get("OPENROUTER_DOUBLE_CHECK", "true").lower() in ("1", "true", "yes", "on")
STRICT_MODE = os.environ.get("STRICT_MODE", "true").lower() in ("1", "true", "yes", "on")
NO_TIME_MODE = os.environ.get("NO_TIME_MODE", "true").lower() in ("1", "true", "yes", "on")
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGES = 5
MIN_SCREENSHOT_WIDTH = int(os.environ.get("MIN_SCREENSHOT_WIDTH", "700"))
MIN_SCREENSHOT_HEIGHT = int(os.environ.get("MIN_SCREENSHOT_HEIGHT", "700"))
TARGET_SCREENSHOT_LONG_EDGE = int(os.environ.get("TARGET_SCREENSHOT_LONG_EDGE", "1800"))
MAX_SCREENSHOT_LONG_EDGE = int(os.environ.get("MAX_SCREENSHOT_LONG_EDGE", "2400"))
BLUR_EDGE_VARIANCE_THRESHOLD = float(os.environ.get("BLUR_EDGE_VARIANCE_THRESHOLD", "90.0"))
USER_AGENT = "ScheduleGenerator/1.0 (local OpenRouter client)"
USAGE_FILE = "usage_stats.json"
KNOWN_SITE_NAMES = [
    "Kuzuha",
    "Baika P",
    "AT Higashi Osaka",
    "AIG Nishiizumigaoka",
    "Ebie",
    "AT Ibarakioda",
    "AIG Terauchi",
    "Luciole Hotarugaike",
    "Frespo Awaza",
    "FT Katano",
    "AM Tsurumi Ryokuchi",
]


def load_dotenv():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_paths = [
        os.path.join(script_dir, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    seen = set()
    for path in candidate_paths:
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        with open(path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def usage_file_path():
    return os.path.join(os.getcwd(), USAGE_FILE)


def default_usage():
    return {
        "totalScans": 0,
        "totalScreenshotScans": 0,
        "totalTextScans": 0,
        "totalImages": 0,
        "byDay": {},
    }


def load_usage():
    path = usage_file_path()
    if not os.path.exists(path):
        return default_usage()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return default_usage()
        usage = default_usage()
        usage.update(data)
        if not isinstance(usage.get("byDay"), dict):
            usage["byDay"] = {}
        return usage
    except Exception:
        return default_usage()


def save_usage(usage):
    with open(usage_file_path(), "w", encoding="utf-8") as handle:
        json.dump(usage, handle, ensure_ascii=False, indent=2)


def record_usage(scan_type, image_count):
    usage = load_usage()
    usage["totalScans"] = int(usage.get("totalScans", 0)) + 1
    usage["totalImages"] = int(usage.get("totalImages", 0)) + int(image_count)
    if scan_type == "screenshot":
        usage["totalScreenshotScans"] = int(usage.get("totalScreenshotScans", 0)) + 1
    elif scan_type == "pasted_text":
        usage["totalTextScans"] = int(usage.get("totalTextScans", 0)) + 1

    today_key = datetime.now().strftime("%Y-%m-%d")
    today_stats = usage["byDay"].get(today_key, {"scans": 0, "images": 0, "textScans": 0})
    today_stats["scans"] = int(today_stats.get("scans", 0)) + 1
    today_stats["images"] = int(today_stats.get("images", 0)) + int(image_count)
    if scan_type == "pasted_text":
        today_stats["textScans"] = int(today_stats.get("textScans", 0)) + 1
    usage["byDay"][today_key] = today_stats
    save_usage(usage)


def get_usage_snapshot():
    usage = load_usage()
    today_key = datetime.now().strftime("%Y-%m-%d")
    today_stats = usage.get("byDay", {}).get(today_key, {"scans": 0, "images": 0, "textScans": 0})
    return {
        "today": {
            "date": today_key,
            "scans": int(today_stats.get("scans", 0)),
            "images": int(today_stats.get("images", 0)),
            "textScans": int(today_stats.get("textScans", 0)),
        },
        "totals": {
            "scans": int(usage.get("totalScans", 0)),
            "screenshotScans": int(usage.get("totalScreenshotScans", 0)),
            "textScans": int(usage.get("totalTextScans", 0)),
            "images": int(usage.get("totalImages", 0)),
        },
    }


class ScheduleHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            self.send_json({
                "ok": True,
                "openrouterConfigured": bool(get_openrouter_api_key()),
                "groqConfigured": bool(get_groq_api_key()),
                "aiConfigured": bool(get_openrouter_api_key() or get_groq_api_key()),
            })
            return
        if self.path == "/api/usage":
            self.send_json(get_usage_snapshot())
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/openrouter-scan-text":
            return self.handle_openrouter_scan_text()
        if self.path != "/api/openrouter-scan":
            self.send_error(404, "Not found")
            return

        if not (get_openrouter_api_key() or get_groq_api_key()):
            self.send_json({"error": "Missing OPENROUTER_API_KEY or GROQ_API_KEY. Add one to the .env file next to server.py and restart python3 server.py."}, 500)
            return

        try:
            fields = parse_multipart_fields(self)
            month = field_value(fields, "month") or ""
            calendar_name = field_value(fields, "calendarName") or "Work Schedule"
            images = field_list(fields, "screenshots")

            if not images:
                self.send_json({"error": "No screenshots uploaded."}, 400)
                return
            if len(images) > MAX_IMAGES:
                self.send_json({"error": f"OpenRouter scan supports up to {MAX_IMAGES} images per scan. Upload fewer screenshots at once."}, 400)
                return

            assets = encode_image_assets(images)
            ai_result = call_schedule_ai_with_fallback(
                prompt_text=schedule_prompt(month, calendar_name),
                image_assets=assets,
                force_json=True,
            )
            events = ai_result["events"]
            events = validate_events_strict(events, month)
            if OPENROUTER_DOUBLE_CHECK and not STRICT_MODE:
                events = double_check_events_with_provider(
                    provider=ai_result["provider"],
                    prompt_text=schedule_prompt(month, calendar_name),
                    image_assets=assets,
                    current_events=events,
                    month=month,
                    calendar_name=calendar_name,
                )
            events = ensure_month_coverage(events, month)
            record_usage(scan_type="screenshot", image_count=len(images))
            self.send_json({
                "events": events,
                "rawText": events_to_text(events),
                "modelRawText": ai_result["text"],
                "providerUsed": ai_result["provider"],
            })
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
        except urllib.error.HTTPError as error:
            try:
                body = error.read().decode("utf-8", "replace") if getattr(error, "fp", None) else str(error)
            except Exception:
                body = str(error)
            self.send_json({"error": f"OpenRouter API error {error.code}: {body}"}, 502)
        except Exception as error:
            self.send_json({"error": str(error)}, 500)

    def handle_openrouter_scan_text(self):
        if not (get_openrouter_api_key() or get_groq_api_key()):
            self.send_json({"error": "Missing OPENROUTER_API_KEY or GROQ_API_KEY. Add one to the .env file next to server.py and restart python3 server.py."}, 500)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length else b"{}"
            payload = json.loads(raw.decode("utf-8", "replace"))
            source_text = str(payload.get("text", "")).strip()
            month = str(payload.get("month", "")).strip()
            calendar_name = str(payload.get("calendarName", "Work Schedule")).strip() or "Work Schedule"

            if not source_text:
                self.send_json({"error": "Text is required."}, 400)
                return

            filtered_text = extract_schedule_only_text(source_text)
            prompt_text = schedule_prompt(month, calendar_name) + "\n\nExtract schedule only from this pasted text. Ignore unrelated text.\n\n" + filtered_text[:70000]
            ai_result = call_schedule_ai_with_fallback(
                prompt_text=prompt_text,
                image_assets=None,
                force_json=True,
            )
            deterministic_events = parse_events_from_schedule_text(filtered_text, month)
            if deterministic_events and not any(not is_day_off_event(event) for event in deterministic_events):
                deterministic_events = []
            events = reconcile_events(deterministic_events, ai_result["events"])
            events = validate_events_strict(events, month)
            # In strict mode, deterministic output is authoritative for pasted text.
            if OPENROUTER_DOUBLE_CHECK and not STRICT_MODE:
                events = double_check_events_with_provider(
                    provider=ai_result["provider"],
                    prompt_text=prompt_text,
                    image_assets=None,
                    current_events=events,
                    month=month,
                    calendar_name=calendar_name,
                )
            events = ensure_month_coverage(events, month)
            record_usage(scan_type="pasted_text", image_count=0)
            self.send_json({
                "events": events,
                "rawText": events_to_text(events),
                "modelRawText": ai_result["text"],
                "providerUsed": ai_result["provider"],
            })
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
        except urllib.error.HTTPError as error:
            try:
                body = error.read().decode("utf-8", "replace") if getattr(error, "fp", None) else str(error)
            except Exception:
                body = str(error)
            self.send_json({"error": f"OpenRouter API error {error.code}: {body}"}, 502)
        except Exception as error:
            self.send_json({"error": str(error)}, 500)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FormField:
    def __init__(self, name, value="", filename="", content_type="", data=b""):
        self.name = name
        self.value = value
        self.filename = filename
        self.type = content_type
        self.file = io.BytesIO(data)


def parse_multipart_fields(handler):
    content_type = handler.headers.get("Content-Type", "")
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if not content_length:
        return {}

    raw_body = handler.rfile.read(content_length)
    message_bytes = (
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {content_length}\r\n"
        "\r\n"
    ).encode("utf-8") + raw_body
    message = BytesParser(policy=email_default_policy).parsebytes(message_bytes)
    fields = {}

    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        content_type = part.get_content_type() or ""
        if filename:
            field = FormField(name=name, filename=filename, content_type=content_type, data=payload)
        else:
            charset = part.get_content_charset() or "utf-8"
            value = payload.decode(charset, "replace")
            field = FormField(name=name, value=value, content_type=content_type, data=payload)

        if name in fields:
            if not isinstance(fields[name], list):
                fields[name] = [fields[name]]
            fields[name].append(field)
        else:
            fields[name] = field

    return fields


def field_value(fields, name):
    if name not in fields:
        return ""
    field = fields[name]
    if isinstance(field, list):
        field = field[0]
    return field.value if not field.filename else ""


def field_list(fields, name):
    if name not in fields:
        return []
    value = fields[name]
    return value if isinstance(value, list) else [value]


def get_openrouter_api_key():
    for name in ("OPENROUTER_API_KEY",):
        value = os.environ.get(name, "").strip()
        if value and value not in ("your_openrouter_api_key_here",):
            return value
    return ""


def get_groq_api_key():
    for name in ("GROQ_API_KEY",):
        value = os.environ.get(name, "").strip()
        if value and value not in ("your_groq_api_key_here",):
            return value
    return ""


def encode_image_assets(images):
    assets = []
    for image in images:
        image.file.seek(0)
        data = image.file.read()
        image.file.seek(0)
        processed = preprocess_screenshot(image.filename, image.type, data)
        encoded = base64.b64encode(processed["data"]).decode("ascii")
        assets.append({
            "filename": image.filename or "",
            "mime": processed["mime"],
            "data_url": f"data:{processed['mime']};base64,{encoded}",
            "preprocessing": processed["metadata"],
        })
    return assets


def preprocess_screenshot(filename, content_type, data):
    if Image is None:
        raise ValueError("Screenshot preprocessing requires Pillow. Run `pip install -r requirements.txt` and restart the server.")

    if not data:
        raise ValueError(f"{filename or 'Screenshot'} is empty.")

    source_mime = content_type or mimetypes.guess_type(filename or "")[0] or ""
    if source_mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError(f"{filename or 'Screenshot'} must be JPG, PNG, or WebP for AI scanning.")

    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.copy()
    except Exception as error:
        raise ValueError(f"{filename or 'Screenshot'} could not be read as an image: {error}")

    original_width, original_height = image.size
    if original_width < MIN_SCREENSHOT_WIDTH or original_height < MIN_SCREENSHOT_HEIGHT:
        raise ValueError(
            f"{filename or 'Screenshot'} is too small ({original_width}x{original_height}). "
            f"Use at least {MIN_SCREENSHOT_WIDTH}x{MIN_SCREENSHOT_HEIGHT} so schedule text is readable."
        )

    blur_score = screenshot_blur_score(image)
    if blur_score < BLUR_EDGE_VARIANCE_THRESHOLD:
        raise ValueError(
            f"{filename or 'Screenshot'} looks blurry or low-detail. "
            "Retake it after zooming in, keeping the schedule text sharp."
        )

    image = normalize_screenshot_image(image)
    processed_data, quality, processed_size = encode_preprocessed_jpeg(image)

    if len(processed_data) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"{filename or 'Screenshot'} is still larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MiB after preprocessing. "
            "Crop to fewer schedule rows or upload a smaller screenshot."
        )

    return {
        "mime": "image/jpeg",
        "data": processed_data,
        "metadata": {
            "originalMime": source_mime,
            "originalWidth": original_width,
            "originalHeight": original_height,
            "processedWidth": processed_size[0],
            "processedHeight": processed_size[1],
            "blurScore": round(blur_score, 2),
            "jpegQuality": quality,
        },
    }


def screenshot_blur_score(image):
    grayscale = ImageOps.grayscale(image)
    grayscale.thumbnail((900, 900), Image.Resampling.LANCZOS)
    laplacian = grayscale.filter(ImageFilter.Kernel(
        (3, 3),
        (0, 1, 0, 1, -4, 1, 0, 1, 0),
        scale=1,
        offset=128,
    ))
    stat = ImageStat.Stat(laplacian)
    return float(stat.var[0] if stat.var else 0.0)


def normalize_screenshot_image(image):
    if image.mode in ("RGBA", "LA") or ("transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        image = background.convert("RGB")
    else:
        image = image.convert("RGB")

    image = resize_for_vision(image)
    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Contrast(image).enhance(1.35)
    image = ImageEnhance.Sharpness(image).enhance(1.55)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=3))
    return image


def resize_for_vision(image):
    width, height = image.size
    long_edge = max(width, height)
    target_long_edge = long_edge
    if long_edge < TARGET_SCREENSHOT_LONG_EDGE:
        target_long_edge = TARGET_SCREENSHOT_LONG_EDGE
    if target_long_edge > MAX_SCREENSHOT_LONG_EDGE:
        target_long_edge = MAX_SCREENSHOT_LONG_EDGE
    if target_long_edge == long_edge:
        return image
    scale = target_long_edge / long_edge
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def encode_preprocessed_jpeg(image):
    current = image
    for max_edge in (max(current.size), 2200, 2000, 1800, 1600):
        if max(current.size) > max_edge:
            current = resize_to_long_edge(current, max_edge)
        for quality in (92, 88, 84, 80, 76, 72):
            output = io.BytesIO()
            current.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
            data = output.getvalue()
            if len(data) <= MAX_IMAGE_BYTES:
                return data, quality, current.size
    return data, quality, current.size


def resize_to_long_edge(image, long_edge):
    width, height = image.size
    current_long_edge = max(width, height)
    if current_long_edge <= long_edge:
        return image
    scale = long_edge / current_long_edge
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def build_openrouter_content(prompt_text, image_assets=None):
    parts = [{
        "type": "text",
        "text": prompt_text,
    }]

    for asset in image_assets or []:
        parts.append({
            "type": "image_url",
            "image_url": {"url": asset["data_url"]},
        })
    return parts


def build_groq_input(prompt_text, image_assets=None):
    content = [{
        "type": "input_text",
        "text": prompt_text,
    }]
    for asset in image_assets or []:
        content.append({
            "type": "input_image",
            "detail": "auto",
            "image_url": asset["data_url"],
        })
    return [{"role": "user", "content": content}]


def schedule_prompt(month, calendar_name):
    return f"""
You are helping convert teacher work schedule screenshots into a clean calendar import.
Read every uploaded screenshot thoroughly and carefully. The goal is to produce clean
schedule events that the app can export into an .ics file matching this style:

BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//EscondeKervin Schedule//EN
CALSCALE:GREGORIAN
X-WR-CALNAME:{calendar_name}
BEGIN:VEVENT
UID:...
DTSTART:20260601T100000
DTEND:20260601T190000
SUMMARY:Kuzuha
END:VEVENT
BEGIN:VEVENT
UID:...
DTSTART;VALUE=DATE:20260604
DTEND;VALUE=DATE:20260604
SUMMARY:Day Off
END:VEVENT
END:VCALENDAR

Use the user's provided CIS/ICS sample as the main reference for output quality.
Match that sample's cleanliness, consistency, and event structure.
Use `/Users/kervinesconde/Desktop/Schedule Generator/june2026v2_schedule.ics` as the canonical naming reference.
Preferred site names from that reference:
- Kuzuha
- Baika P
- AT Higashi Osaka
- AIG Nishiizumigaoka
- Ebie
- AT Ibarakioda
- AIG Terauchi
- Luciole Hotarugaike
- Frespo Awaza
- FT Katano
- AM Tsurumi Ryokuchi
- Day Off

Schedule month: {month}
Calendar name: {calendar_name}

Return only this JSON object, with no markdown and no explanation:
{{
  "events": [
    {{
      "date": "YYYY-MM-DD",
      "allDay": false,
      "start": "HH:MM",
      "end": "HH:MM",
      "title": "Location or work site name"
    }},
    {{
      "date": "YYYY-MM-DD",
      "allDay": true,
      "start": "",
      "end": "",
      "title": "Day Off"
    }}
  ]
}}

Rules:
- Accuracy is the top priority. This is not a summary task; it is schedule data extraction.
- Do not hallucinate. Only output schedule facts that are visible in the uploaded screenshot or pasted schedule text.
- Never invent a school/location, time, date, or work block because it seems likely from the month pattern.
- If a site name is not clearly readable, keep only the readable characters or leave that row out for review; do not guess the full school name.
- Do not use the preferred site-name list to create missing entries. The list is only for spelling when the screenshot visibly matches that school.
- If the screenshot does not visibly show a second school for a date, do not add one.
- If the screenshot visibly shows a second timestamp or second school for the same date, include it exactly as visible.
- When uncertain between two possible readings, choose the one directly supported by the screenshot text, not the one that seems common.
- Before returning JSON, inspect every uploaded screenshot row by row and date by date.
- Carefully read the date, start time, end time, and site/location title for each visible schedule block.
- Cross-check overlapping screenshots so repeated dates are not duplicated and missed rows are not skipped.
- Monthly schedule mode: always return the whole selected month.
- If a date has no visible school/schedule entry (blank, empty, "-", off), treat it as Day Off.
- Auto-fill missing dates in the selected month as Day Off so no date is skipped.
- If a row is partially cut off, blurry, or uncertain, use nearby context only when it clearly confirms the date/time/title.
- Do not guess a site name or time that is not visible enough to read.
- When text is ambiguous, prefer the most accurate readable value and keep the title concise.
- The final JSON should be clean enough to import directly into Calendar without manual cleanup, except for rare unreadable screenshot text.
- Check the screenshot thoroughly before answering. Small OCR mistakes are common.
- Clean the event data so it is ready for .ics export like the sample above.
- Use 24-hour time.
- Split one date into multiple events when the screenshot shows multiple work sites or time ranges.
- For off days, rest days, blanks marked off, holidays, or clear no-work days, use title "Day Off" and allDay true.
- If a visible schedule date has a blank schedule cell/row with no time and no work site, that date is considered Day Off.
- If the date is visible but its schedule details are blank, return one all-day event for that date: title "Day Off", allDay true, start "", end "".
- If a row is visible but not readable enough, use Day Off for that date instead of dropping the date.
- Do not create Day Off events for dates that are not visible in the screenshots or for cropped/unknown areas.
- A date with a real timed work schedule is not Day Off, even if another overlapping screenshot shows that same date blank or repeated.
- The title must be only the work site/location/name, such as "Kuzuha", "Baika P", or "AT Higashi Osaka".
- Do not include weekday names, dates, time ranges, labels, notes, or extra punctuation in title.
- Preserve exact capitalization and spacing of site names when readable.
- Name quality is critical: write site/location names as accurately as possible from the screenshot.
- Do not rewrite, shorten, or "fix" names unless the screenshot clearly supports that spelling.
- If the same site appears multiple times in the month, keep its name spelling consistent across all events.
- When one screenshot is blurry but the same name appears clearly on another date/screenshot, use the clearer spelling.
- If a name is partially unreadable, keep the readable portion and avoid inventing letters.
- Before finalizing JSON, quickly re-check that site names are consistent and free of obvious OCR typos.
- If a date has two shifts or two locations, return two separate JSON objects for that same date.
- Same-day multiple schedules are valid when the time range or title/location is different.
- Critical rule: if one date shows two separate time ranges (two timestamps), that means two work blocks and must include both site names.
  Do not collapse two timestamps into one site name. Keep both schools/locations in the final result.
  Example: 2026-06-05 10:00-15:00 AIG Nishiizumigaoka and 2026-06-05 15:00-19:00 Ebie are two real events.
- If the screenshot text shows:
  06/05 10:00-15:00 AIG Nishiizumigaoka
  06/05 15:00-19:00 Ebie
  then return exactly two events, both dated 2026-06-05. Do not create events for 06/06, 06/07, or any other date from these two lines.
- Never spread one date's shifts across other dates. A date applies only to the schedule rows where that same date is visible, unless the screenshot clearly uses a single date header for a grouped block.
- If every visible row says 06/05, all returned events from those rows must be dated 2026-06-05.
- Do not create a second event only because the same date appears twice in the screenshot, table, header, or OCR text.
- Uploaded screenshots may overlap or show the same schedule dates more than once. If the same date appears in different screenshots, compare the rows and keep only one final copy of each real schedule block.
- Across all screenshots combined, each exact date/time/location work block should appear only once in the final JSON.
- Across all screenshots combined, each Day Off date should appear only once.
- Do not duplicate dates from different screenshots. A repeated date in another screenshot is not a new event unless it shows a different visible time range or a different visible site/location for that date.
- For one date, count the actual work blocks: each event must have its own visible time range and visible site/location title.
- A duplicate is only when date, allDay, start, end, and title are the same or clearly the same entry repeated in another screenshot.
  Example duplicate: 2026-06-05 10:00-15:00 AIG Nishiizumigaoka appears twice. Return it once.
- If two entries have the same date and same time range, treat them as duplicates unless the screenshot clearly shows two separate simultaneous jobs.
- If a date has any timed work event, do not also return "Day Off" for that same date.
- If the same date has two different rows, do not merge them unless they are clearly the exact same shift.
- If the schedule shows a normal full-day work block such as 10:00-19:00, return it as a timed event, not all-day.
- If a time is visible but slightly ambiguous, choose the most likely time from the screenshot context.
- Do not invent events that are not visible.
- Never invent rows that are not explicit in the screenshot.
- Do not include duplicate events.
- Return the events sorted by date and start time.
""".strip()


class AIProviderError(Exception):
    def __init__(self, provider, message, code=None):
        super().__init__(message)
        self.provider = provider
        self.code = code


def call_openrouter(api_key, content, force_json=True):
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{
            "role": "user",
            "content": content,
        }],
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 4096,
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "HTTP-Referer": "http://localhost:4173",
            "X-Title": "Schedule Generator",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        if error.code == 429:
            raise AIProviderError("openrouter", "OpenRouter rate limit hit (429). Wait about 1 minute and try again, or use the backup provider.", 429)
        raise AIProviderError("openrouter", f"OpenRouter API error {error.code}: {body}", error.code)


def call_groq(api_key, input_payload):
    payload = {
        "model": GROQ_MODEL,
        "input": input_payload,
        "temperature": 0,
        "max_output_tokens": 4096,
    }
    request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        if error.code == 429:
            raise AIProviderError("groq", "Groq rate limit hit (429). Wait about 1 minute and try again.", 429)
        raise AIProviderError("groq", f"Groq API error {error.code}: {body}", error.code)


def extract_response_text(result):
    if isinstance(result, dict):
        output_text = result.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
    choices = result.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            chunks = []
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    chunks.append(part["text"])
            if chunks:
                return "\n".join(chunks)
    return json.dumps(result)


def extract_response_text_from_output(result):
    if isinstance(result, dict) and isinstance(result.get("output"), list):
        chunks = []
        for item in result["output"]:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    chunks.append(content["text"])
        if chunks:
            return "\n".join(chunks)
    return extract_response_text(result)


def should_fallback_to_groq(error):
    if not isinstance(error, AIProviderError):
        return False
    return error.provider == "openrouter" and (error.code == 429 or (isinstance(error.code, int) and error.code >= 500))


def call_schedule_ai_with_fallback(prompt_text, image_assets=None, force_json=True, preferred_provider="openrouter"):
    providers = []
    ordered = [preferred_provider, "groq" if preferred_provider == "openrouter" else "openrouter"]
    for provider in ordered:
        if provider == "openrouter" and get_openrouter_api_key() and provider not in providers:
            providers.append(provider)
        if provider == "groq" and get_groq_api_key() and provider not in providers:
            providers.append(provider)

    if not providers:
        raise ValueError("Missing OPENROUTER_API_KEY or GROQ_API_KEY. Add one to the .env file next to server.py and restart python3 server.py.")

    last_error = None
    for provider in providers:
        try:
            if provider == "openrouter":
                result = call_openrouter(
                    get_openrouter_api_key(),
                    build_openrouter_content(prompt_text, image_assets),
                    force_json=force_json,
                )
                text = extract_response_text(result)
            else:
                result = call_groq(
                    get_groq_api_key(),
                    build_groq_input(prompt_text, image_assets),
                )
                text = extract_response_text_from_output(result)

            events = parse_json_events(text)
            return {
                "provider": provider,
                "result": result,
                "text": text,
                "events": events,
            }
        except AIProviderError as error:
            last_error = error
            continue
        except ValueError as error:
            last_error = error
            continue

    raise ValueError(str(last_error) if last_error else "No AI provider configured.")


def parse_json_events(text):
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("Empty AI response.")

    # Try direct parse first.
    parse_attempts = [cleaned]

    # Try fenced code block payload.
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE)
    parse_attempts.extend(fenced)

    # Try balanced JSON object/array extraction from noisy text.
    parse_attempts.extend(extract_json_candidates(cleaned))

    data = None
    last_error = None
    for candidate in parse_attempts:
        candidate = str(candidate or "").strip()
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            break
        except Exception as error:
            last_error = error
            continue

    if data is None:
        raise ValueError(f"Could not parse AI response JSON: {last_error}")

    if isinstance(data, dict) and isinstance(data.get("events"), list):
        data = data["events"]
    if not isinstance(data, list):
        raise ValueError("OpenRouter returned JSON, but not a list of events.")
    normalized = [normalize_event(item) for item in data]
    return combine_events_by_date(dedupe_events(normalized))


def extract_json_candidates(text):
    decoder = json.JSONDecoder()
    candidates = []
    for match in re.finditer(r"[\{\[]", str(text or "")):
        idx = match.start()
        try:
            obj, end = decoder.raw_decode(text[idx:])
            snippet = text[idx:idx + end]
            if isinstance(obj, (dict, list)):
                candidates.append(snippet)
        except Exception:
            continue
    return candidates


def safe_parse_json_events(text):
    try:
        return parse_json_events(text)
    except Exception:
        # AI can occasionally return malformed JSON; caller may fallback deterministically.
        return []


def normalize_event(item):
    all_day = bool(item.get("allDay"))
    title = str(item.get("title", "Teaching Schedule")).strip() or "Teaching Schedule"
    start = str(item.get("start", "")).strip()
    end = str(item.get("end", "")).strip()
    date_value = str(item.get("date", "")).strip()
    title_is_off = bool(re.search(r"\b(day\s*off|off|holiday|blank|empty|no\s*schedule)\b", title, re.IGNORECASE))
    time_is_off = start in ("-", "—", "–") and end in ("-", "—", "–")

    if title in ("-", "—", "–"):
        title_is_off = True
    if time_is_off:
        title_is_off = True
    if not all_day and (not start or not end):
        all_day = True
    if title_is_off:
        all_day = True

    if all_day:
        if title_is_off:
            title = "Day Off"
        else:
            title = normalize_site_name(title)
        start = ""
        end = ""
    else:
        title = normalize_site_name(title)

    return {
        "date": date_value,
        "allDay": all_day,
        "start": "" if all_day else start,
        "end": "" if all_day else end,
        "title": title,
        "notes": "Scanned with OpenRouter AI",
    }


def normalize_site_name(title):
    cleaned = re.sub(r"\s+", " ", str(title or "").strip())
    cleaned = re.sub(r"\b(mon|tue|wed|thu|fri|sat|sun)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}[\/.-]\d{1,2}(?:[\/.-]\d{2,4})?\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\s*(?:-|to|~|〜)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b", " ", cleaned)
    cleaned = re.sub(r"\b(day\s*off|off|holiday|schedule|shift|work)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -/|")
    if not cleaned:
        return "Teaching Schedule"

    # Preserve multi-site titles such as "AIG Nishiizumigaoka / Ebie".
    if "/" in cleaned:
        parts = [part.strip() for part in cleaned.split("/") if part.strip()]
        normalized_parts = [normalize_site_name(part) for part in parts]
        normalized_parts = [part for part in normalized_parts if part and part != "Teaching Schedule"]
        if normalized_parts:
            deduped = []
            seen = set()
            for part in normalized_parts:
                key = part.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(part)
            return " / ".join(deduped)
        return "Teaching Schedule"

    # Match common OCR variations to known site names.
    known_lower_map = {name.lower(): name for name in KNOWN_SITE_NAMES}
    if cleaned.lower() in known_lower_map:
        return known_lower_map[cleaned.lower()]

    return cleaned


def extract_schedule_only_text(source_text):
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(source_text or "").splitlines()]
    lines = [line for line in lines if line]
    kept = []
    for line in lines:
        has_date = bool(re.search(r"\b\d{1,2}[\/.-]\d{1,2}(?:[\/.-]\d{2,4})?\b", line))
        has_time = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\s*(?:-|to|~|〜)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b", line))
        has_off = bool(re.search(r"\b(day\s*off|off|holiday|blank|empty|no\s*schedule|-)\b", line, re.IGNORECASE))
        has_site_keyword = bool(re.search(r"\b(aig|at|ft|am|luciole|frespo|kuzuha|ebie|baika)\b", line, re.IGNORECASE))
        has_day_marker = bool(re.match(r"^\d{1,2}$", line))
        has_school_text = bool(re.search(r"[A-Za-z]{2,}", line)) and not bool(re.search(r"^(mon|tue|wed|thu|fri|sat|sun)\b", line, re.IGNORECASE))
        if has_date or has_time or has_off or has_site_keyword or has_day_marker or has_school_text:
            kept.append(line)
    return "\n".join(kept) if kept else str(source_text or "")


def parse_events_from_schedule_text(source_text, month_value):
    year = None
    month_hint = None
    if re.match(r"^\d{4}-\d{2}$", str(month_value or "")):
        year, month_hint = month_value.split("-")
        year = int(year)
        month_hint = int(month_hint)

    events = []
    current_iso_date = ""
    for raw in str(source_text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue

        date_match = re.search(r"\b(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?\b", line)
        if not date_match:
            # Day marker only like "01" means selected month day.
            day_marker = re.match(r"^(\d{1,2})$", line)
            if day_marker and month_hint and year:
                day_value = int(day_marker.group(1))
                if 1 <= day_value <= 31:
                    current_iso_date = f"{year:04d}-{month_hint:02d}-{day_value:02d}"
                continue
            # If no date on this line, reuse current day context from previous marker/date row.
            if current_iso_date:
                iso_date = current_iso_date
                off_line = bool(re.search(r"\b(day\s*off|off|holiday|blank|empty|no\s*schedule|-)\b", line, re.IGNORECASE))
                time_match = re.search(
                    r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?\s*(?:-|to|~|〜)\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?\b",
                    line
                )
                if off_line and not time_match:
                    events.append({
                        "date": iso_date,
                        "allDay": True,
                        "start": "",
                        "end": "",
                        "title": "Day Off",
                        "notes": "Deterministic text parse"
                    })
                    continue

                title = line
                if time_match:
                    title = title.replace(time_match.group(0), " ")
                title = normalize_site_name(title)
                if not title or title == "Teaching Schedule":
                    continue
                events.append({
                    "date": iso_date,
                    "allDay": True if NO_TIME_MODE else False,
                    "start": "",
                    "end": "",
                    "title": title,
                    "notes": "Deterministic text parse",
                })
            continue

        m1 = int(date_match.group(1))
        d1 = int(date_match.group(2))
        y1 = date_match.group(3)
        event_year = int(y1) + 2000 if y1 and len(y1) == 2 else (int(y1) if y1 else (year or 2026))

        # Assume MM/DD unless first token cannot be month.
        if 1 <= m1 <= 12:
            event_month, event_day = m1, d1
        else:
            event_month, event_day = d1, m1

        if month_hint and event_month != month_hint:
            # keep if explicit year+month present, otherwise skip likely noise
            if not y1:
                continue

        iso_date = f"{event_year:04d}-{event_month:02d}-{event_day:02d}"
        current_iso_date = iso_date

        off_line = bool(re.search(r"\b(day\s*off|off|holiday|blank|empty|no\s*schedule|-)\b", line, re.IGNORECASE))
        time_match = re.search(
            r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?\s*(?:-|to|~|〜)\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)?\b",
            line
        )

        if off_line and not time_match:
            events.append({
                "date": iso_date,
                "allDay": True,
                "start": "",
                "end": "",
                "title": "Day Off",
                "notes": "Deterministic text parse"
            })
            continue

        title = line
        title = title.replace(date_match.group(0), " ")
        if time_match:
            title = title.replace(time_match.group(0), " ")
        title = normalize_site_name(title)
        if not title or title == "Teaching Schedule":
            continue

        events.append({
            "date": iso_date,
            "allDay": True if NO_TIME_MODE else False,
            "start": "",
            "end": "",
            "title": title,
            "notes": "Deterministic text parse",
        })

    if not events:
        return []
    return combine_events_by_date(dedupe_events(events))


def to_24h(hour, minute, meridiem, fallback=""):
    if hour > 24 or minute > 59:
        return ""
    h = hour
    m = minute
    mer = meridiem.lower()
    if not mer and fallback:
        mer = fallback
    if mer == "pm" and h < 12:
        h += 12
    if mer == "am" and h == 12:
        h = 0
    if h > 23:
        return ""
    return f"{h:02d}:{m:02d}"


def reconcile_events(deterministic_events, ai_events):
    combined = list(deterministic_events or []) + list(ai_events or [])
    if not combined:
        return []

    work_dates = {
        event.get("date")
        for event in combined
        if not is_day_off_event(event)
    }
    filtered = [
        event for event in combined
        if not (is_day_off_event(event) and event.get("date") in work_dates)
    ]
    return combine_events_by_date(dedupe_events(filtered))


def is_day_off_event(event):
    return bool(event.get("allDay")) and bool(
        re.search(r"\bday\s*off\b", str(event.get("title", "")), re.IGNORECASE)
    )


def validate_events_strict(events, month_value):
    """Hard validation gate for final schedule quality."""
    month_hint = None
    year_hint = None
    if re.match(r"^\d{4}-\d{2}$", str(month_value or "")):
        year_hint, month_hint = month_value.split("-")
        year_hint = int(year_hint)
        month_hint = int(month_hint)

    validated = []
    for event in events:
        date_value = str(event.get("date", "")).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_value):
            continue
        y, m, d = [int(x) for x in date_value.split("-")]
        if month_hint and m != month_hint:
            continue
        if year_hint and y != year_hint:
            continue
        if d < 1 or d > 31:
            continue

        all_day = bool(event.get("allDay"))
        title = str(event.get("title", "")).strip()
        start = str(event.get("start", "")).strip()
        end = str(event.get("end", "")).strip()
        is_day_off = bool(re.search(r"\b(day\s*off|off|holiday)\b", title, re.IGNORECASE))

        if all_day and is_day_off:
            title = "Day Off"
            start = ""
            end = ""
        else:
            if NO_TIME_MODE:
                all_day = True
                start = ""
                end = ""
            elif not re.match(r"^\d{2}:\d{2}$", start) or not re.match(r"^\d{2}:\d{2}$", end):
                continue
            title = normalize_site_name(title)
            if not title or title == "Teaching Schedule":
                continue

        validated.append({
            "date": date_value,
            "allDay": all_day,
            "start": start,
            "end": end,
            "title": title,
            "notes": event.get("notes", ""),
        })

    if not validated:
        return []
    return combine_events_by_date(dedupe_events(validated))


def double_check_events_with_provider(provider, prompt_text, image_assets, current_events, month, calendar_name):
    """Second-pass AI verification to improve final accuracy."""
    verification_prompt = {
        "type": "text",
        "text": (
            "Double-check these extracted events against the provided source.\n"
            "Fix wrong dates, times, day-off status, duplicate blocks, and location names.\n"
            "Do not hallucinate. Remove any event, school, or time that is not directly supported by the source.\n"
            "Do not add missing-looking entries unless the source visibly shows them.\n"
            "Enforce this strictly: if one date has two separate time ranges, output two work blocks with both site names.\n"
            "Do not drop the second school/location when two timestamps exist for the same date.\n"
            "Keep only schedule data. Return JSON object with key 'events' only.\n"
            "Do not add explanations.\n"
            f"Schedule month: {month}\n"
            f"Calendar name: {calendar_name}\n"
            f"Current events JSON:\n{json.dumps({'events': current_events}, ensure_ascii=False)}"
        ),
    }
    try:
        verify_text = f"{prompt_text}\n\n{verification_prompt['text']}"
        result = call_schedule_ai_with_fallback(
            prompt_text=verify_text,
            image_assets=image_assets,
            force_json=True,
            preferred_provider=provider,
        )
        text = result["text"]
        checked = parse_json_events(text)
        if checked:
            return checked
    except Exception:
        # Keep original extraction if verification fails.
        pass
    return current_events


def dedupe_events(events):
    seen = set()
    unique = []
    dates_with_work = {event.get("date") for event in events if not event.get("allDay")}
    for event in sorted(events, key=event_sort_key):
        if event.get("allDay") and event.get("date") in dates_with_work:
            continue
        key = event_identity(event)
        if key in seen:
            continue
        if same_time_duplicate(unique, event):
            continue
        seen.add(key)
        unique.append(event)
    return unique


def combine_events_by_date(events):
    grouped = {}
    for event in events:
        event_date = str(event.get("date", "")).strip()
        if not event_date:
            continue
        event["date"] = event_date
        grouped.setdefault(event_date, []).append(event)

    combined = []
    for date, day_events in grouped.items():
        timed = [event for event in day_events if not event.get("allDay")]
        all_day_schools = [
            e for e in day_events
            if e.get("allDay") and not re.search(r"\bday\s*off\b", str(e.get("title", "")), re.IGNORECASE)
        ]
        if not timed:
            day_offs = [e for e in day_events if re.search(r"\bday\s*off\b", str(e.get("title", "")), re.IGNORECASE)]
            schools = [e for e in day_events if not re.search(r"\bday\s*off\b", str(e.get("title", "")), re.IGNORECASE)]
            if schools:
                merged_title = " / ".join(unique_titles([str(e.get("title", "")) for e in schools]))
                combined.append({
                    "date": date,
                    "allDay": True,
                    "start": "",
                    "end": "",
                    "title": merged_title or "Teaching Schedule",
                    "notes": " | ".join(str(e.get("notes", "")).strip() for e in schools if str(e.get("notes", "")).strip()),
                })
            else:
                combined.append({
                    "date": date,
                    "allDay": True,
                    "start": "",
                    "end": "",
                    "title": "Day Off" if day_offs else "Teaching Schedule",
                    "notes": "Scanned with OpenRouter AI",
                })
            continue

        timed_sorted = sorted(timed, key=lambda event: normalize_time(event.get("start", "")))
        merged_title = " / ".join(unique_titles(
            [event.get("title", "") for event in timed_sorted] +
            [event.get("title", "") for event in all_day_schools]
        ))
        merged_notes = " | ".join(
            event.get("notes") or f"{event.get('start', '')}-{event.get('end', '')} {event.get('title', '')}".strip()
            for event in timed_sorted
        )
        if all_day_schools:
            extra_notes = " | ".join(str(event.get("notes", "")).strip() for event in all_day_schools if str(event.get("notes", "")).strip())
            if extra_notes:
                merged_notes = f"{merged_notes} | {extra_notes}" if merged_notes else extra_notes
        combined.append({
            "date": date,
            "allDay": False,
            "start": timed_sorted[0].get("start", ""),
            "end": timed_sorted[-1].get("end", ""),
            "title": merged_title or timed_sorted[0].get("title", ""),
            "notes": merged_notes,
        })

    return sorted(combined, key=event_sort_key)


def unique_titles(titles):
    seen = set()
    result = []
    for title in titles:
        normalized = normalize_title(title)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(title.strip())
    return result


def same_time_duplicate(existing_events, candidate):
    if candidate.get("allDay"):
        return False
    for event in existing_events:
        if event.get("allDay"):
            continue
        if event.get("date") != candidate.get("date"):
            continue
        if normalize_time(event.get("start")) != normalize_time(candidate.get("start")):
            continue
        if normalize_time(event.get("end")) != normalize_time(candidate.get("end")):
            continue
        if titles_are_close(event.get("title", ""), candidate.get("title", "")):
            return True
    return False


def titles_are_close(left, right):
    left_title = normalize_title(left)
    right_title = normalize_title(right)
    return left_title == right_title


def event_identity(event):
    return (
        event.get("date", "").strip(),
        bool(event.get("allDay")),
        normalize_time(event.get("start", "")),
        normalize_time(event.get("end", "")),
        normalize_title(event.get("title", "")),
    )


def event_sort_key(event):
    return (
        event.get("date", ""),
        "00:00" if event.get("allDay") else normalize_time(event.get("start", "")),
        normalize_title(event.get("title", "")),
    )


def normalize_time(value):
    return str(value or "").strip()


def normalize_title(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def events_to_text(events):
    lines = []
    for event in events:
        date = event["date"][5:].replace("-", "/") if len(event["date"]) >= 10 else event["date"]
        if event["allDay"]:
            lines.append(f"{date} {event['title']}")
        else:
            lines.append(f"{date} {event['start']}-{event['end']} {event['title']}")
    return "\n".join(lines)


def ensure_month_coverage(events, month_value):
    if not re.match(r"^\d{4}-\d{2}$", str(month_value or "")):
        return events

    year_str, month_str = month_value.split("-")
    year = int(year_str)
    month = int(month_str)
    if month < 1 or month > 12:
        return events

    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    from datetime import date as _date
    days_in_month = (_date(next_year, next_month, 1) - _date(year, month, 1)).days

    by_date = {}
    for event in events:
        by_date.setdefault(event.get("date"), []).append(event)

    completed = list(events)
    for day in range(1, days_in_month + 1):
        iso = f"{year:04d}-{month:02d}-{day:02d}"
        if iso in by_date:
            continue
        completed.append({
            "date": iso,
            "allDay": True,
            "start": "",
            "end": "",
            "title": "Day Off",
            "notes": "Auto-filled missing date",
        })

    return sorted(completed, key=event_sort_key)


if __name__ == "__main__":
    load_dotenv()
    server = ThreadingHTTPServer(("", PORT), ScheduleHandler)
    print(f"Schedule Generator running at http://localhost:{PORT}")
    if not get_openrouter_api_key() and not get_groq_api_key():
        print("No AI key configured: add OPENROUTER_API_KEY=... or GROQ_API_KEY=... to the .env file next to server.py and restart.")
    elif get_openrouter_api_key() and get_groq_api_key():
        print("OpenRouter primary, Groq fallback enabled.")
    elif get_groq_api_key():
        print("Groq fallback enabled.")
    else:
        print("OpenRouter primary enabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        sys.exit(0)
