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
You are generating the daily HTML news digest for The Malta Gazette, dated {date_string}.

Research the latest available information using web search. Cover:
1. Maltese local news — politics, courts, environment, health, transport, business, culture.
2. Maltese courtroom updates — current proceedings, key testimony, verdicts.
3. European and international news — major stories relevant to Malta and Europe.
4. Technology and gadgets — AI, cybersecurity, consumer tech, major companies.
5. Malta 5-day weather forecast — temperatures, conditions, UV index, any advisories.

Use reputable, current sources. Do not invent facts, quotes, dates, statistics, or links.

OUTPUT RULES — follow exactly:
- Return a complete HTML document starting with <!doctype html> and ending with </html>.
- Do NOT include a <style> block, any CSS, or Markdown fences.
- Do NOT include JavaScript, forms, ads, or tracking pixels.
- Do NOT use fabricated image URLs — omit all <img> tags entirely.
- Do NOT add any text outside the HTML tags.

Use EXACTLY this HTML structure and class names — copy it precisely:

<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The Malta Gazette — {date_string}</title>
</head>
<body>
<div class="container">

  <header class="masthead">
    <p class="masthead-kicker">The Daily Edition</p>
    <h1>The Malta Gazette</h1>
    <div class="publication-bar">
      <span>Vol. CXXIV</span>
      <span>[DAY, DD MONTH YYYY]</span>
      <span>Malta &amp; International Edition</span>
    </div>
  </header>

  <div class="summary-box">
    [One or two sentence front-page summary of the day's biggest stories.]
  </div>

  <div class="page-body">

    <div class="lead-story">
      <div class="lead-text">
        <span class="story-tag">[Category] · [Tag]</span>
        <h2>[Lead story headline]</h2>
        <p>[Dateline and body paragraph 1]</p>
        <p>[Body paragraph 2]</p>
        <a href="[URL]" class="source-link">Further reading: [Source name] →</a>
      </div>
    </div>

    <div class="section-heading">
      <span class="section-heading-label">🇲🇹 Maltese Local News</span>
    </div>
    <div class="story-grid">
      <div class="story-card">
        <span class="story-tag">Malta Local</span>
        <h3>[Headline]</h3>
        <p>[Summary]</p>
        <a href="[URL]" class="source-link">Source: [Name] →</a>
      </div>
      [2 or more additional .story-card divs for Maltese local stories]
    </div>

    <div class="section-heading">
      <span class="section-heading-label">⚖️ Courtroom Updates</span>
    </div>
    <div class="story-grid">
      <div class="story-card">
        <span class="story-tag">Courts</span>
        <h3>[Headline]</h3>
        <p>[Summary]</p>
        <a href="[URL]" class="source-link">Source: [Name] →</a>
      </div>
      [1 or more additional .story-card divs for court stories]
    </div>

    <div class="section-heading">
      <span class="section-heading-label">🌍 European &amp; International News</span>
    </div>
    <div class="story-grid">
      <div class="story-card">
        <span class="story-tag">Europe</span>
        <h3>[Headline]</h3>
        <p>[Summary]</p>
        <a href="[URL]" class="source-link">Source: [Name] →</a>
      </div>
      [2 or more additional .story-card divs for international stories]
    </div>

    <div class="section-heading">
      <span class="section-heading-label">💻 Technology &amp; Gadgets</span>
    </div>
    <div class="story-grid">
      <div class="story-card">
        <span class="story-tag">Technology</span>
        <h3>[Headline]</h3>
        <p>[Summary]</p>
        <a href="[URL]" class="source-link">Source: [Name] →</a>
      </div>
      [2 or more additional .story-card divs for tech stories]
    </div>

    <div class="section-heading">
      <span class="section-heading-label">☀️ Malta Weather Forecast</span>
    </div>
    <div class="weather-card">
      <div class="weather-card-hero">
        <div class="weather-hero-left">
          <div class="weather-hero-icon">[TODAY EMOJI e.g. ☀️]</div>
          <div>
            <div class="weather-hero-temp">[TODAY HIGH e.g. 33°C]</div>
            <div class="weather-hero-label">Valletta, Malta</div>
            <div class="weather-hero-desc">[Condition] — UV Index: [level]</div>
          </div>
        </div>
        <div class="weather-hero-alert">
          [EMOJI] <strong>[Advisory headline if any, else "Clear Conditions"]</strong><br>
          [One sentence advisory or general forecast note.]
        </div>
      </div>
      <div class="weather-days">
        <div class="weather-day">
          <span class="weather-day-name">[Mon]</span>
          <span class="weather-day-icon">[☀️]</span>
          <span class="weather-day-date">[DD Mon]</span>
          <span class="weather-day-hi">[33°]</span>
          <span class="weather-day-lo">[26°]</span>
        </div>
        [4 more .weather-day divs, one per day of the 5-day forecast]
      </div>
      <p class="weather-source">Source: Malta International Airport Met Office.</p>
    </div>

  </div>
</div>
</body>
</html>

Replace every [placeholder] with real researched content. Do not output the bracket placeholders.
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
    Strip reasoning preamble, Markdown fences, embedded styles, and unsafe elements.

    The prompt instructs Gemini to use the site's external stylesheet and not
    include a <style> block, but this provides a defensive cleanup before the
    generated page is published. Removing <style> prevents the digest's CSS
    from bleeding into the host index.html when the content is injected via JS.
    """
    document = document.strip()

    document = re.sub(
        r"^\s*```(?:html)?\s*",
        "",
        document,
        flags=re.IGNORECASE,
    )
    document = re.sub(r"\s*```\s*$", "", document)

    # Gemini sometimes prefixes the response with its reasoning/thinking
    # notes before the actual document, and may add stray text after the
    # closing </html> tag. The reasoning text may itself mention HTML tags
    # (e.g. inside backticks), so find the *last* doctype/html occurrence,
    # which marks the start of the real document.
    doctype_matches = list(re.finditer(r"<!doctype\s+html", document, flags=re.IGNORECASE))
    html_matches = list(re.finditer(r"<html\b", document, flags=re.IGNORECASE))
    start_candidates = [m.start() for m in (doctype_matches[-1:] or []) + (html_matches[-1:] or [])]
    if start_candidates:
        document = document[min(start_candidates):]

    end_matches = list(re.finditer(r"</html\s*>", document, flags=re.IGNORECASE))
    if end_matches:
        document = document[: end_matches[-1].end()]

    # Remove script, iframe, object, embed, form, and style elements.
    document = re.sub(
        r"<(script|style|iframe|object|embed|form)\b[^>]*>.*?</\1\s*>",
        "",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    document = re.sub(
        r"<(script|style|iframe|object|embed|form)\b[^>]*/?>",
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

# ---------------------------------------------------------------------------
# Image injection — Wikimedia Commons live search
# ---------------------------------------------------------------------------

# Skip file types that won't render as photos in a browser.
_SKIP_EXTENSIONS = {".svg", ".pdf", ".ogg", ".webm", ".mp4", ".ogv", ".tif", ".tiff"}

def _commons_search(query: str, width: int = 800) -> str | None:
    """
    Search Wikimedia Commons for a photo matching *query* and return a
    thumbnail URL, or None if nothing suitable is found.
    """
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,          # File: namespace only
        "gsrlimit": 10,
        "prop": "imageinfo",
        "iiprop": "url|mediatype|mime",
        "iiurlwidth": width,
        "format": "json",
    })
    url = f"https://commons.wikimedia.org/w/api.php?{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DailyGazette/1.0 (https://github.com/robertcassar18/daily-gazette)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        title = page.get("title", "")
        ext = "." + title.rsplit(".", 1)[-1].lower() if "." in title else ""
        if ext in _SKIP_EXTENSIONS:
            continue
        info_list = page.get("imageinfo", [])
        if not info_list:
            continue
        info = info_list[0]
        mime = info.get("mime", "")
        if not mime.startswith("image/"):
            continue
        # Skip SVG even if MIME says image
        if "svg" in mime or "svg" in title.lower():
            continue
        thumb = info.get("thumburl", "")
        if thumb:
            return thumb
    return None


def _build_query(tag: str, headline: str) -> str:
    """
    Build a Wikimedia Commons search query from the story tag and headline.
    Extracts the most meaningful nouns (capitalised words, proper nouns,
    country/topic names) and combines them with the tag for specificity.
    """
    # Strip markup-style separators from tags like "Breaking · Courts"
    tag_clean = re.sub(r"\s*[·|—]\s*", " ", tag).strip()

    # Pull capitalised words from the headline (likely nouns/proper names)
    proper = re.findall(r"\b([A-Z][a-z]{2,})\b", headline)
    # Drop very common words that add no search value
    stop = {"The", "For", "New", "And", "After", "Over", "With", "From", "Into",
            "Amid", "That", "This", "Has", "Its", "Are", "Was", "Were", "By",
            "Amid", "Amid", "Faces", "Surpasses", "Launches", "Unveils",
            "Raises", "Approved", "Announced", "Charged", "Walks", "Free",
            "Thwarts", "Imposes", "Reporting", "High", "Profile"}
    keywords = [w for w in proper if w not in stop][:4]

    # Also pull the first significant lowercase noun phrase (e.g. "fishing", "earthquake")
    subject_words = re.findall(
        r"\b(fishing|earthquake|nuclear|heatwave|desalination|organ|donation|"
        r"cybersecurity|instagram|parliament|migration|flooding|drought|"
        r"hospital|transport|airport|railway|solar|energy|missile|military|"
        r"sanctions|summit|vaccine|inflation|budget|election|protest|fire|flood)\b",
        headline, re.IGNORECASE
    )
    keywords += [w.capitalize() for w in subject_words[:2]]

    # Specific overrides for topics where generic queries work better
    headline_lower = headline.lower()
    if "fishing" in headline_lower or "fishermen" in headline_lower:
        return "Malta fishing boat harbour"
    if "instagram" in headline_lower:
        return "smartphone social media app icon"
    if "desalination" in headline_lower or "water" in headline_lower and "plant" in headline_lower:
        return "desalination water plant sea"
    if "earthquake" in headline_lower:
        return "earthquake disaster rescue rubble"
    if "ukraine" in headline_lower:
        return "Ukraine Kyiv city flag"
    if "poland" in headline_lower:
        return "Poland Warsaw city flag"
    if "colombia" in headline_lower:
        return "Colombia Bogota city"
    if "organ donation" in headline_lower:
        return "hospital medicine healthcare Malta"

    parts = [tag_clean] + keywords
    return " ".join(dict.fromkeys(parts))  # preserve order, deduplicate


# Fallback queries used when the Commons search returns nothing useful,
# indexed by tag keyword (lowercase match).
_FALLBACK_QUERIES: dict[str, str] = {
    "malta":          "Malta Valletta aerial",
    "local":          "Malta Valletta",
    "courts":         "Malta Valletta Courts Justice building",
    "court":          "Malta Valletta Courts Justice building",
    "europe":         "European Union parliament Brussels building",
    "international":  "United Nations headquarters New York aerial",
    "world":          "world globe earth",
    "technology":     "computer technology laptop screen",
    "tech":           "technology circuit board computer",
    "ai":             "artificial intelligence robot",
    "cybersecurity":  "cybersecurity network security padlock",
    "gadgets":        "consumer electronics gadgets smartphone",
    "environment":    "nature environment forest green",
    "infrastructure": "construction infrastructure bridge crane",
    "business":       "business finance office meeting",
    "fishing":        "Malta fishing boat harbour",
    "health":         "hospital medicine healthcare doctor",
    "transport":      "Malta bus transport road",
    "politics":       "parliament politics government",
    "breaking":       "news journalism press camera",
    "weather":        "Malta sunshine blue sky Mediterranean",
    "earthquake":     "earthquake disaster rubble rescue",
    "military":       "military army soldiers",
    "energy":         "energy power plant electricity",
    "social media":   "smartphone mobile app screen",
}

def _fallback_query(tag: str) -> str:
    tag_lower = tag.lower()
    for key, query in _FALLBACK_QUERIES.items():
        if key in tag_lower:
            return query
    return "Malta news Valletta"


def inject_images(document: str) -> str:
    """
    Insert a contextually relevant image into every .story-card and into
    the .lead-story by searching Wikimedia Commons with a query built from
    each card's story-tag and headline text. Falls back to a tag-based
    generic query if the specific search returns nothing.
    """
    # ── Lead story feature image ──────────────────────────────────────────
    lead_tag_m = re.search(
        r'class="lead-story".*?class="story-tag"[^>]*>([^<]+)<.*?<h2[^>]*>([^<]+)<',
        document, re.IGNORECASE | re.DOTALL,
    )
    if lead_tag_m:
        lead_tag = lead_tag_m.group(1).strip()
        lead_headline = lead_tag_m.group(2).strip()
        lead_query = _build_query(lead_tag, lead_headline)
        lead_url = _commons_search(lead_query, width=900)
        if not lead_url:
            lead_url = _commons_search(_fallback_query(lead_tag), width=900)
    else:
        lead_url = _commons_search("Malta Valletta news", width=900)

    if lead_url:
        lead_img = (
            f'\n      <figure class="feature-image">'
            f'<img src="{html.escape(lead_url)}" '
            f'alt="Lead story illustration" loading="lazy"></figure>'
        )
        document = re.sub(
            r'(<div class="lead-story">)',
            r'\1' + lead_img,
            document, count=1, flags=re.IGNORECASE,
        )

    # ── Story card images ─────────────────────────────────────────────────
    def replace_card(match: re.Match) -> str:
        card_html = match.group(0)
        tag_m = re.search(
            r'class="story-tag"[^>]*>([^<]+)<', card_html, re.IGNORECASE
        )
        h3_m = re.search(
            r'<h3[^>]*>([^<]+)<', card_html, re.IGNORECASE
        )
        tag_text = tag_m.group(1).strip() if tag_m else ""
        headline_text = h3_m.group(1).strip() if h3_m else ""

        # Try three progressively broader queries
        queries = [
            _build_query(tag_text, headline_text),
            _fallback_query(tag_text),
            _fallback_query(tag_text).split()[0] + " photo",
        ]
        img_url = None
        for q in queries:
            img_url = _commons_search(q)
            if img_url:
                break
        if not img_url:
            return card_html  # No image rather than a broken one

        img_tag = (
            f'<img src="{html.escape(img_url)}" '
            f'alt="{html.escape(tag_text)}: {html.escape(headline_text[:60])}" '
            f'loading="lazy">\n        '
        )
        return re.sub(
            r'(<div class="story-card">)\s*',
            r'\1\n        ' + img_tag,
            card_html, count=1, flags=re.IGNORECASE,
        )

    document = re.sub(
        r'<div class="story-card">.*?</div>',
        replace_card,
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return document

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
    generated_html = inject_images(generated_html)

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