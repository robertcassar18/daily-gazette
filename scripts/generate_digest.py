#!/usr/bin/env python3

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Malta")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)

ROOT = Path(__file__).resolve().parent.parent
FORCE_RUN = os.environ.get("FORCE_RUN", "0") == "1"

def now_in_malta() -> datetime:
    return datetime.now(TIMEZONE)

def should_run() -> bool:
    """
    Scheduled GitHub jobs run at 08:00 and 09:00 UTC.

    Only proceed when the local Malta hour is 10. Manual workflow
    dispatches bypass this check.
    """
    if FORCE_RUN:
        return True

    current = now_in_malta()

    if current.hour != 10:
        print(
            f"Skipping: local Europe/Malta time is "
            f"{current.strftime('%Y-%m-%d %H:%M:%S %Z')}, not 10:00."
        )
        return False

    return True

def build_prompt(date_string: str) -> str:
    return f"""
Create today's complete HTML newspaper-style news digest for {date_string}.

The digest must focus on the following areas:

1. Maltese local news
   - Give Maltese news prominent coverage.
   - Include politics, public affairs, business, transport, courts,
     environment, health, education, culture, and other significant
     local developments where relevant.

2. European and international news
   - Include a high-level overview of important European-wide news.
   - Include major international stories that are relevant to readers
     in Malta and Europe.

3. Technology and gadgets
   - Include global technology news.
   - Cover important companies, software, artificial intelligence,
     cybersecurity, consumer electronics, gadgets, products, and trends.

4. Space
   - Include significant spaceflight, astronomy, NASA, ESA, launch,
     satellite, and space science news.

Research the latest available information using web search. Prefer
reputable, current sources. Do not invent facts, quotations, images,
dates, statistics, or links.

Create a polished, self-contained HTML document styled like a traditional
newspaper. Use inline CSS only; do not require a separate stylesheet.

The page should include:

- A newspaper masthead.
- The publication date.
- A short front-page summary.
- Clearly separated sections.
- Newspaper-like columns and typography.
- A prominent lead story.
- Article headlines, summaries, and source links.
- Appropriate images where reliable direct image URLs are available.
- Alt text for every image.
- Captions for images where appropriate.
- A "Further reading" link for each article.
- A small footer explaining that links point to the original sources.

Use only valid HTML. Return the complete HTML document, beginning with
<!doctype html> and ending with </html>.

Do not return Markdown fences.
Do not discuss how you generated the page.
Do not include JavaScript.
Do not include forms, tracking pixels, advertisements, or affiliate links.
Do not use fabricated image URLs. If no reliable image is available for
an article, omit its image rather than inventing a URL.
""".strip()

def call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it as a GitHub Actions secret."
        )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ],
        "tools": [
            {
                "google_search": {}
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 30000,
        },
    }

    query = urllib.parse.urlencode({"key": api_key})
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Gemini API returned HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to Gemini API: {exc}") from exc

    candidates = response_data.get("candidates", [])

    if not candidates:
        raise RuntimeError(
            "Gemini returned no candidates:\n"
            + json.dumps(response_data, indent=2)
        )

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ]

    result = "\n".join(text_parts).strip()

    if not result:
        raise RuntimeError("Gemini returned an empty response.")

    return result

def clean_generated_html(document: str) -> str:
    """
    Remove accidental Markdown fences and potentially unsafe elements.

    The prompt already asks Gemini not to include JavaScript, but this
    provides a defensive cleanup before publishing the generated page.
    """
    document = document.strip()

    document = re.sub(
        r"^\s*```(?:html)?\s*",
        "",
        document,
        flags=re.IGNORECASE,
    )
    document = re.sub(r"\s*```\s*$", "", document)

    # Remove script, iframe, object, embed, and form elements.
    document = re.sub(
        r"<(script|iframe|object|embed|form)\b[^>]*>.*?</\1\s*>",
        "",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    document = re.sub(
        r"<(script|iframe|object|embed|form)\b[^>]*/?>",
        "",
        document,
        flags=re.IGNORECASE,
    )

    # Remove inline event handlers such as onclick= and onerror=.
    document = re.sub(
        r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
        "",
        document,
        flags=re.IGNORECASE,
    )

    # Remove javascript: URLs.
    document = re.sub(
        r"""(\s(?:href|src|action)\s*=\s*["'])\s*javascript:[^"']*(["'])""",
        r"\1#\2",
        document,
        flags=re.IGNORECASE,
    )

    if "<html" not in document.lower():
        raise RuntimeError("Gemini did not return a complete HTML document.")

    return document.strip() + "\n"

def digest_files():
    return sorted(
        ROOT.glob("daily-????-??-??.html"),
        key=lambda path: path.name,
        reverse=True,
    )

def build_index() -> str:
    files = digest_files()

    if not files:
        raise RuntimeError("No daily digest files were found.")

    options = []
    for path in files:
        date_part = path.stem.removeprefix("daily-")
        try:
            display_date = datetime.strptime(
                date_part, "%Y-%m-%d"
            ).strftime("%A, %d %B %Y")
        except ValueError:
            display_date = date_part

        options.append(
            f'        <option value="{html.escape(path.name)}">'
            f"{html.escape(display_date)}</option>"
        )

    latest_file = files[0].name
    latest_label = files[0].stem.removeprefix("daily-")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Daily Maltese, European, international, technology, gadget, and space news digest">
  <title>Daily News Digest</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1d1d1d;
      --paper: #f6f1e7;
      --line: #262626;
      --muted: #666;
      --accent: #8d1f1f;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: Georgia, "Times New Roman", serif;
    }}

    header {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 2rem 1rem 1rem;
      text-align: center;
      border-bottom: 4px double var(--line);
    }}

    .kicker {{
      margin: 0 0 .4rem;
      color: var(--accent);
      font: 700 .8rem/1.2 Arial, sans-serif;
      letter-spacing: .18em;
      text-transform: uppercase;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(2.4rem, 7vw, 5.5rem);
      line-height: .95;
      text-transform: uppercase;
      letter-spacing: -.04em;
    }}

    .subheading {{
      margin: .8rem 0 0;
      color: var(--muted);
      font-style: italic;
    }}

    .controls {{
      max-width: 1180px;
      margin: 1rem auto;
      padding: 0 1rem;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: .7rem;
      font-family: Arial, sans-serif;
    }}

    .controls label {{
      font-size: .9rem;
      font-weight: 700;
    }}

    select {{
      max-width: 100%;
      padding: .55rem .7rem;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      font: inherit;
    }}

    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 0 1rem 2rem;
    }}

    .edition-date {{
      margin: 0 0 .75rem;
      color: var(--muted);
      font: .8rem Arial, sans-serif;
      letter-spacing: .08em;
      text-align: right;
      text-transform: uppercase;
    }}

    .digest-frame {{
      display: block;
      width: 100%;
      min-height: 78vh;
      border: 1px solid var(--line);
      background: white;
    }}

    footer {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 1rem;
      border-top: 4px double var(--line);
      color: var(--muted);
      font: .8rem/1.5 Arial, sans-serif;
      text-align: center;
    }}
  </style>
</head>
<body>
  <header>
    <p class="kicker">The Daily Edition</p>
    <h1>Daily News Digest</h1>
    <p class="subheading">Malta · Europe · World · Technology · Space</p>
  </header>

  <div class="controls">
    <label for="edition">Edition:</label>
    <select id="edition" aria-label="Choose a news edition">
{chr(10).join(options)}
    </select>
  </div>

  <main>
    <p class="edition-date" id="edition-date">Edition: {html.escape(latest_label)}</p>
    <iframe
      class="digest-frame"
      id="digest"
      title="Selected daily news digest"
      src="{html.escape(latest_file)}">
    </iframe>
  </main>

  <footer>
    News links lead to the original publishers and sources.
  </footer>

  <script>
    const selector = document.getElementById("edition");
    const digest = document.getElementById("digest");
    const editionDate = document.getElementById("edition-date");

    selector.addEventListener("change", function () {{
      const selectedFile = selector.value;
      digest.src = selectedFile;
      editionDate.textContent =
        "Edition: " + selectedFile.replace("daily-", "").replace(".html", "");
      history.replaceState(null, "", "#" + selectedFile);
    }});

    const hashFile = decodeURIComponent(location.hash.slice(1));
    if (hashFile && [...selector.options].some(option => option.value === hashFile)) {{
      selector.value = hashFile;
      digest.src = hashFile;
      editionDate.textContent =
        "Edition: " + hashFile.replace("daily-", "").replace(".html", "");
    }}
  </script>
</body>
</html>
"""

def main():
    if not should_run():
        return

    current = now_in_malta()
    date_string = current.strftime("%Y-%m-%d")
    output_path = ROOT / f"daily-{date_string}.html"

    print(f"Generating digest for {date_string} using model {MODEL}...")

    prompt = build_prompt(date_string)
    generated_html = call_gemini(prompt)
    generated_html = clean_generated_html(generated_html)

    output_path.write_text(generated_html, encoding="utf-8")
    print(f"Wrote {output_path.name}")

    index_html = build_index()
    (ROOT / "index.html").write_text(index_html, encoding="utf-8")
    print("Wrote index.html")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)