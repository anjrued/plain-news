"""
Plain News — hourly generation pipeline
Fetches RSS headlines, ranks by urgency via Claude, writes articles, rebuilds site.
"""

import os
import json
import feedparser
import anthropic
from datetime import datetime, timezone
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────────────

CATEGORIES = {
    "world": {
        "label": "World",
        "feeds": [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        ],
    },
    "us": {
        "label": "U.S.",
        "feeds": [
            "https://feeds.npr.org/1001/rss.xml",
            "https://feeds.bbci.co.uk/news/rss.xml",
        ],
    },
    "business": {
        "label": "Business",
        "feeds": [
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        ],
    },
    "tech": {
        "label": "Tech",
        "feeds": [
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://techcrunch.com/feed/",
        ],
    },
    "science": {
        "label": "Science",
        "feeds": [
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        ],
    },
}

HEADLINES_PER_CATEGORY = 12   # how many headlines to send Claude per category
CARDS_PER_CATEGORY     = 5    # grid cards shown below the hero
OUTPUT_DIR             = Path(__file__).parent.parent   # repo root
ARTICLES_DIR           = OUTPUT_DIR / "articles"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ── RSS FETCHING ─────────────────────────────────────────────────────────────

def fetch_headlines(feeds: list[str], limit: int = HEADLINES_PER_CATEGORY) -> list[dict]:
    """Pull entries from a list of RSS feeds, deduplicate by title."""
    seen, entries = set(), []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                entries.append({
                    "title":   title,
                    "summary": entry.get("summary", entry.get("description", ""))[:400],
                    "link":    entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            print(f"  Feed error ({url}): {e}")
    return entries[:limit]


# ── CLAUDE EDITORIAL ENGINE ──────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the editorial engine for Plain, a clean ad-free news site.
Your job: identify the most important current story from a list of headlines and write clear,
factual, neutral articles about it.

Editorial priorities (in order):
1. URGENCY — what is actively unfolding right now takes priority over background stories.
2. CONSEQUENCE — decisions, events, or developments that change something real for real people.
3. SCOPE — how many people are meaningfully affected.

Avoid: sensationalism, outrage bait, celebrity news, conflict for its own sake.
Write in plain, direct English. No jargon. No padding. No em dashes."""


def generate_category_content(category_key: str, category_label: str, headlines: list[dict]) -> dict:
    """Ask Claude to rank headlines and write the hero article + card summaries."""

    headlines_text = "\n".join(
        f"{i+1}. {h['title']}\n   {h['summary'][:200]}"
        for i, h in enumerate(headlines)
    )

    prompt = f"""Here are the current top headlines for the {category_label} category:

{headlines_text}

Tasks:
1. Identify the single most important/urgent story from this list.
2. Write a 420-480 word factual article about it suitable for the hero position.
3. Write 2-sentence summaries for the next {CARDS_PER_CATEGORY} most important stories (different from the hero).

Return ONLY valid JSON in exactly this format:
{{
  "hero": {{
    "headline": "...",
    "body": "...",
    "urgency_score": <integer 1-10>
  }},
  "cards": [
    {{"headline": "...", "summary": "..."}},
    {{"headline": "...", "summary": "..."}},
    {{"headline": "...", "summary": "..."}},
    {{"headline": "...", "summary": "..."}},
    {{"headline": "...", "summary": "..."}}
  ]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    data["category_key"]   = category_key
    data["category_label"] = category_label
    return data


# ── HTML GENERATION ──────────────────────────────────────────────────────────

def now_et() -> str:
    """Current time formatted as '3:00 PM ET'."""
    from datetime import datetime
    import time
    # Simple UTC-4 offset for ET (handles most of the year; good enough for a news ticker)
    et_hour = (datetime.utcnow().hour - 4) % 24
    suffix = "AM" if et_hour < 12 else "PM"
    display = et_hour % 12 or 12
    return f"{display}:00 {suffix} ET"


def render_index(all_categories: list[dict], front_hero_cat: str) -> str:
    """Build the full index.html with live content."""

    timestamp = now_et()

    # Pick the front page hero (highest urgency_score among category heroes)
    hero_data = max(all_categories, key=lambda c: c["hero"].get("urgency_score", 0))
    hero = hero_data["hero"]
    hero_slug = slug(hero["headline"])

    # Build card HTML for all non-hero categories
    cards_html = ""
    for cat in all_categories:
        for card in cat["cards"]:
            card_slug = slug(card["headline"])
            cards_html += f"""
      <a class="article-card fade-in" href="articles/{cat['category_key']}/{card_slug}.html" data-cat="{cat['category_key']}">
        <span class="card-tag">{cat['category_label']}</span>
        <h2 class="card-headline">{card['headline']}</h2>
        <p class="card-summary">{card['summary']}</p>
        <span class="card-time">{timestamp}</span>
      </a>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Plain - News without the noise</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,500;0,9..144,600;1,9..144,300&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="style.css">
</head>
<body>

  <header>
    <div class="header-inner">
      <a href="/" class="wordmark">plain</a>
      <nav class="category-nav">
        <button class="cat-btn active" data-cat="all">All</button>
        <button class="cat-btn" data-cat="world">World</button>
        <button class="cat-btn" data-cat="us">U.S.</button>
        <button class="cat-btn" data-cat="business">Business</button>
        <button class="cat-btn" data-cat="tech">Tech</button>
        <button class="cat-btn" data-cat="science">Science</button>
      </nav>
      <div class="header-actions">
        <button class="theme-toggle" id="themeToggle" aria-label="Toggle theme">&#9790;</button>
        <button class="support-btn" onclick="document.getElementById('support').scrollIntoView({{behavior:'smooth'}})">Support Plain</button>
      </div>
    </div>
  </header>

  <div class="update-bar">
    Updated at <strong>{timestamp}</strong> &mdash; Next update in <strong id="countdown">57 min</strong>
  </div>

  <main>
    <section class="hero fade-in">
      <a href="articles/{hero_data['category_key']}/{hero_slug}.html">
        <span class="tag">{hero_data['category_label']}</span>
        <h1>{hero['headline']}</h1>
        <p class="hero-summary">{hero['body'][:320].rstrip()}...</p>
        <span class="meta">Today, {timestamp}</span>
      </a>
    </section>

    <p class="section-label">Latest</p>

    <div class="articles-grid" id="articlesGrid">
      {cards_html}
    </div>

    <div class="support-box" id="support">
      <div class="support-box-text">
        <p>Plain is free to read. No ads. No agenda.</p>
        <span>If it is worth something to you, a small contribution keeps it running.</span>
      </div>
      <button class="support-box-btn">Support Plain</button>
    </div>
  </main>

  <footer>
    <div class="footer-inner">
      <span class="footer-wordmark">plain</span>
      <span class="footer-tagline">Updated every hour. No ads. No noise. Always free.</span>
      <div class="footer-links">
        <a href="#">About</a>
        <a href="#support">Support</a>
        <a href="#">Contact</a>
      </div>
    </div>
  </footer>

  <script src="main.js"></script>
</body>
</html>"""


def render_article(cat_key: str, cat_label: str, headline: str, body: str, timestamp: str) -> str:
    """Build an individual article page."""
    paragraphs = "".join(f"<p>{para.strip()}</p>" for para in body.split("\n\n") if para.strip())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{headline} - Plain</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,500;0,9..144,600;1,9..144,300&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../../style.css">
</head>
<body>

  <header>
    <div class="header-inner">
      <a href="/" class="wordmark">plain</a>
      <nav class="category-nav">
        <button class="cat-btn active" data-cat="all">All</button>
        <button class="cat-btn" data-cat="world">World</button>
        <button class="cat-btn" data-cat="us">U.S.</button>
        <button class="cat-btn" data-cat="business">Business</button>
        <button class="cat-btn" data-cat="tech">Tech</button>
        <button class="cat-btn" data-cat="science">Science</button>
      </nav>
      <div class="header-actions">
        <button class="theme-toggle" id="themeToggle" aria-label="Toggle theme">&#9790;</button>
      </div>
    </div>
  </header>

  <main class="article-page">
    <a href="/" class="back-link">&larr; Back to Plain</a>
    <span class="tag">{cat_label}</span>
    <h1 class="article-headline">{headline}</h1>
    <p class="article-meta">{timestamp}</p>
    <div class="article-body">
      {paragraphs}
    </div>
    <p class="article-note">This article was written by Plain's AI editorial engine based on reporting from wire services.</p>
  </main>

  <footer>
    <div class="footer-inner">
      <span class="footer-wordmark">plain</span>
      <span class="footer-tagline">Updated every hour. No ads. No noise. Always free.</span>
      <div class="footer-links">
        <a href="/">Home</a>
        <a href="/#support">Support</a>
      </div>
    </div>
  </footer>

  <script src="../../main.js"></script>
</body>
</html>"""


# ── UTILITIES ─────────────────────────────────────────────────────────────────

def slug(text: str) -> str:
    """Convert headline to URL-safe slug."""
    import re
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80]


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    ARTICLES_DIR.mkdir(exist_ok=True)
    timestamp = now_et()
    all_categories = []

    for cat_key, cat_config in CATEGORIES.items():
        print(f"Processing: {cat_config['label']}...")
        headlines = fetch_headlines(cat_config["feeds"])
        if not headlines:
            print(f"  No headlines found for {cat_config['label']}, skipping.")
            continue

        try:
            data = generate_category_content(cat_key, cat_config["label"], headlines)
            all_categories.append(data)
            print(f"  Hero: {data['hero']['headline'][:60]}... (urgency: {data['hero'].get('urgency_score')})")

            # Write hero article page
            cat_dir = ARTICLES_DIR / cat_key
            cat_dir.mkdir(exist_ok=True)
            hero_html = render_article(
                cat_key, cat_config["label"],
                data["hero"]["headline"], data["hero"]["body"], timestamp
            )
            hero_path = cat_dir / f"{slug(data['hero']['headline'])}.html"
            hero_path.write_text(hero_html, encoding="utf-8")

            # Write card article pages (stub pages — body is the summary for now)
            for card in data["cards"]:
                card_html = render_article(
                    cat_key, cat_config["label"],
                    card["headline"], card["summary"], timestamp
                )
                card_path = cat_dir / f"{slug(card['headline'])}.html"
                card_path.write_text(card_html, encoding="utf-8")

        except Exception as e:
            print(f"  Claude error for {cat_config['label']}: {e}")
            continue

    if not all_categories:
        print("No categories generated. Aborting.")
        return

    # Rebuild index.html
    index_html = render_index(all_categories, all_categories[0]["category_key"])
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"\nDone. {len(all_categories)} categories, {sum(len(c['cards']) for c in all_categories)} card articles.")
    print(f"Front page hero: {max(all_categories, key=lambda c: c['hero'].get('urgency_score', 0))['hero']['headline'][:70]}...")


if __name__ == "__main__":
    main()
