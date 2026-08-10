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

ROOT = Path(__file__).resolve().parent.parent
FORCE_RUN = os.environ.get("FORCE_RUN", "0") == "1"

class QuotaExceededError(RuntimeError):
    pass

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

def get_free_model_candidates(api_key: str) -> list[str]:
    """
    Return stable generateContent models sorted from newest to oldest version.

    Excludes preview, lite, audio, tts, and live variants. The caller should
    try models in order and skip any that return a quota error.
    """
    models_url = "https://generativelanguage.googleapis.com/v1beta/models"
    query = urllib.parse.urlencode({"key": api_key})
    request = urllib.request.Request(
        f"{models_url}?{query}",
        headers={"Content-Type": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Failed to fetch Gemini models (HTTP {exc.code}): {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not connect to Gemini API to fetch models: {exc}"
        ) from exc

    models = response_data.get("models", [])
    candidates = []

    for model in models:
        # name is like "models/gemini-2.5-flash"
        model_name = model.get("name", "")
        supported_methods = model.get("supportedGenerationMethods", [])

        # Extract the model ID (remove "models/" prefix)
        model_id = model_name.split("/")[-1] if model_name else ""
        
        if not model_id:
            continue

        # Filter for models with generateContent support
        if "generateContent" not in supported_methods:
            continue

        # Exclude previews, lite, audio, tts, and live variants
        if any(
            part in model_id.lower()
            for part in ["preview", "lite", "audio", "tts", "live"]
        ):
            continue

        candidates.append(model_id)

    # Exclude deprecated models that are no longer available to new users.
    # Some accounts cannot access older releases (for example: gemini-2.5-flash).
    deprecated_models = {"gemini-2.5-flash", "gemini-2.5"}
    candidates = [c for c in candidates if not any(d in c for d in deprecated_models)]

    if not candidates:
        raise RuntimeError(
            "No free-tier Gemini models with generateContent support found. "
            "Available models from API: " + json.dumps([m.get("name", "").split("/")[-1] for m in models])
        )

    # Sort by version number (extract major.minor and compare)
    def extract_version(model_name: str) -> tuple:
        # e.g., "gemini-3.6-flash" -> (3, 6)
        match = re.search(r"gemini-(\d+)\.(\d+)", model_name)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return (0, 0)

    candidates.sort(key=extract_version, reverse=True)
    return candidates

def build_prompt(date_string: str) -> str:
    return f"""
Create today's complete HTML newspaper-style news digest for {date_string}.

The digest must focus on the following areas:

1. Maltese local news
   - Give Maltese news prominent coverage.
   - Include politics, public affairs, business, transport, courts,
     environment, health, education, culture, and other significant
     local developments where relevant.
    
2. Maltese Courtroom Updates
   - Give a digest of the current courtroom proceedings.
   - Include any salient details and highlights that have come out.

3. European and international news
   - Include a high-level overview of important European-wide news.
   - Include major international stories that are relevant to readers
     in Malta and Europe.

4. Technology and gadgets
   - Include global technology news.
   - Cover important companies, software, artificial intelligence,
     cybersecurity, consumer electronics, gadgets, products, and trends.

5. Space
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

def call_gemini(prompt: str, model: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it as a GitHub Actions secret."
        )

    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
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
        f"{api_url}?{query}",
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
        if exc.code == 429:
            raise QuotaExceededError(
                f"Quota exceeded for model {model}: {error_body}"
            ) from exc
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
        ROOT.glob("news_archive/daily-????-??-??.html"),
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

        relative_path = path.relative_to(ROOT).as_posix()
        options.append(
            f'        <option value="{html.escape(relative_path)}">'
            f"{html.escape(display_date)}</option>"
        )

    latest_file = files[0].relative_to(ROOT).as_posix()
    latest_label = files[0].stem.removeprefix("daily-")

    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Daily Maltese, European, international, technology, gadget, and space news digest">
  <title>Daily News Digest</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="top-ribbon">
    <div class="ribbon-brand">
      <span class="logo-mark">DND</span>
      <div class="logo-copy">
        <p class="kicker">The Daily Edition</p>
        <h1>Daily News Digest</h1>
        <p>Malta · Europe · World · Technology · Space</p>
      </div>
    </div>
    <div class="ribbon-controls">
      <label for="edition">Edition</label>
      <select id="edition" aria-label="Choose a news edition">
{OPTIONS}
      </select>
    </div>
  </div>

  <div class="page-shell">
    <main class="content-card">
      <div class="digest-content" id="digest-content" aria-live="polite"></div>
    </main>
  </div>

  <footer>
    News links lead to the original publishers and sources.
  </footer>

  <script>
    const selector = document.getElementById("edition");
    const digestContent = document.getElementById("digest-content");

    function formatEditionLabel(file) {
      return file
        .split("/")
        .pop()
        .replace("daily-", "")
        .replace(".html", "");
    }

    function renderEdition(file) {
      digestContent.innerHTML = '<p class="edition-date">Loading edition…</p>';

      fetch(file)
        .then((response) => {
          if (!response.ok) {
            throw new Error("Unable to load edition");
          }
          return response.text();
        })
        .then((html) => {
          const doc = new DOMParser().parseFromString(html, "text/html");
          const container = doc.querySelector(".container");

          digestContent.innerHTML = "";

          if (container) {
            const clonedContainer = container.cloneNode(true);
            clonedContainer.querySelector(".masthead")?.remove();
            digestContent.appendChild(clonedContainer);
          } else {
            const fallback = document.createElement("div");
            fallback.className = "digest-simple";
            fallback.innerHTML = (doc.body?.innerHTML || html).trim() || "<p>The selected edition could not be rendered.</p>";
            digestContent.appendChild(fallback);
          }

          history.replaceState(null, "", "#" + file);
          digestContent.insertAdjacentHTML(
            "afterbegin",
            `<p class="edition-date">Edition: ${formatEditionLabel(file)}</p>`
          );
        })
        .catch(() => {
          digestContent.innerHTML = '<p class="edition-date">The selected edition could not be loaded.</p>';
        });
    }

    selector.addEventListener("change", function () {
      renderEdition(selector.value);
    });

    const hashFile = decodeURIComponent(location.hash.slice(1));
    if (hashFile && [...selector.options].some((option) => option.value === hashFile)) {
      selector.value = hashFile;
    }

    renderEdition(selector.value);
  </script>
</body>
</html>
""".replace("{OPTIONS}", chr(10).join(options))

def main():
    if not should_run():
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it as a GitHub Actions secret."
        )

    print("Detecting available free-tier Gemini models...")
    candidates = get_free_model_candidates(api_key)
    print(f"Candidates (newest first): {', '.join(candidates)}")

    current = now_in_malta()
    date_string = current.strftime("%Y-%m-%d")
    output_path = ROOT / "news_archive" / f"daily-{date_string}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating digest for {date_string}...")

    prompt = build_prompt(date_string)
    generated_html = None
    for model in candidates:
        print(f"Trying model: {model}")
        try:
            generated_html = call_gemini(prompt, model)
            print(f"Using model: {model}")
            break
        except QuotaExceededError as exc:
            print(f"Quota exceeded for {model}, trying next candidate...")
            continue

    if generated_html is None:
        raise RuntimeError(
            "All candidate models returned quota errors. "
            f"Tried: {', '.join(candidates)}"
        )

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