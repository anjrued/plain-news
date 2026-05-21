"""
Plain News - hourly generation pipeline
Fetches RSS headlines, ranks by urgency via Claude, writes articles, rebuilds site.
"""

import os
import json
import re
import feedparser
import anthropic
from datetime import datetime
from pathlib import Path

# -- CONFIG --

CATEGORIES = {
    "world": {
        "label": "World",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        ],
    },
    "us": {
        "label": "U.S.",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.npr.org/1001/rss.xml",
            "https://feeds.bbci.co.uk/news/rss.xml",
        ],
    },
    "business": {
        "label": "Business",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        ],
    },
    "tech": {
        "label": "Tech",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://techcrunch.com/feed/",
        ],
    },
    "science": {
        "label": "Science",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        ],
    },
    "sports": {
        "label": "Sports",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
            "https://www.espn.com/espn/rss/news",
            "https://feeds.bbci.co.uk/sport/rss.xml",
        ],
    },
}

HEADLINES_PER_CATEGORY = 12
CARDS_PER_CATEGORY     = 5
OUTPUT_DIR             = Path(__file__).parent.parent

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# -- RSS FETCHING --

def fetch_headlines(feeds, limit=HEADLINES_PER_CATEGORY):
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
                })
        except Exception as e:
            print(f"  Feed error ({url}): {e}")
    return entries[:limit]


# -- CLAUDE EDITORIAL ENGINE --

SYSTEM_PROMPT = """You are the editorial engine for Plain, a clean ad-free news site.
Identify the most important current story and write clear, factual, neutral articles.

Editorial priorities (in order):
1. URGENCY - what is actively unfolding right now.
2. CONSEQUENCE - decisions or events that change something real.
3. SCOPE - how many people are meaningfully affected.

Avoid: sensationalism, outrage bait, celebrity news.
Write in plain direct English. No jargon. No padding. No em dashes."""


def generate_category_content(category_key, category_label, headlines):
    headlines_text = "\n".join(
        f"{i+1}. {h['title']}\n   {h['summary'][:200]}"
        for i, h in enumerate(headlines)
    )

    prompt = f"""Here are the current top headlines for the {category_label} category:

{headlines_text}

Tasks:
1. Identify the single most important/urgent story.
2. Write a 420-480 word factual article for the hero position.
3. For the next {CARDS_PER_CATEGORY} most important stories write:
   - teaser: one sentence card preview
   - body: two short paragraphs (~120 words) expanding on the story
   - urgency_score: integer 1-10 using the same criteria as the hero

Return ONLY valid JSON:
{{
  "hero": {{
    "headline": "...",
    "body": "full article text with paragraph breaks",
    "urgency_score": <1-10>
  }},
  "cards": [
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>}}
  ]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    data["category_key"]   = category_key
    data["category_label"] = category_label
    return data


# -- HTML GENERATION --

def now_et():
    et_hour = (datetime.utcnow().hour - 4) % 24
    suffix  = "AM" if et_hour < 12 else "PM"
    display = et_hour % 12 or 12
    return f"{display}:00 {suffix} ET"


def make_paragraphs(text):
    return "".join(
        f"<p>{p.strip()}</p>"
        for p in text.split("\n\n")
        if p.strip()
    )


def render_index(all_categories):
    timestamp = now_et()
    top_cat   = max(all_categories, key=lambda c: c["hero"].get("urgency_score", 0))

    # -- Hero sections (one per category + "all") --
    def hero_section(cat_key, cat_label, hero, visible):
        display    = "" if visible else ' style="display:none"'
        fade       = " fade-in" if visible else ""
        preview    = hero["body"][:380].rstrip()
        paragraphs = make_paragraphs(hero["body"])
        return f"""
    <section class="hero{fade}" data-cat-hero="{cat_key}"{display}>
      <span class="tag">{cat_label}</span>
      <h1>{hero["headline"]}</h1>
      <p class="hero-summary">{preview}...</p>
      <div class="hero-foot">
        <span class="meta">Today, {timestamp}</span>
        <button class="expand-btn" onclick="toggleExpand(this)">Continue reading &darr;</button>
      </div>
      <div class="article-expand hero-expand">
        <div class="hero-expand-body">{paragraphs}</div>
        <button class="collapse-btn" onclick="collapseThis(this)">Close &uarr;</button>
      </div>
    </section>"""

    heroes_html  = hero_section("all", top_cat["category_label"], top_cat["hero"], visible=True)
    for cat in all_categories:
        heroes_html += hero_section(cat["category_key"], cat["category_label"], cat["hero"], visible=False)

    # -- Card grid -- collected across all categories, sorted by urgency --
    all_cards = []
    for cat in all_categories:
        for card in cat["cards"]:
            all_cards.append({
                **card,
                "cat_key":   cat["category_key"],
                "cat_label": cat["category_label"],
            })
    all_cards.sort(key=lambda c: c.get("urgency_score", 0), reverse=True)

    cards_html = ""
    for card in all_cards:
        teaser = card.get("teaser", card.get("summary", ""))
        body   = card.get("body", card.get("summary", ""))
        card_paragraphs = make_paragraphs(body)
        ck = card["cat_key"]
        cl = card["cat_label"]
        cards_html += f"""
      <div class="article-card fade-in" data-cat="{ck}">
        <span class="card-tag">{cl}</span>
        <h2 class="card-headline">{card["headline"]}</h2>
        <p class="card-summary">{teaser}</p>
        <div class="card-foot">
          <span class="card-time">{timestamp}</span>
          <button class="expand-btn" onclick="toggleExpand(this)">Continue reading &darr;</button>
        </div>
        <div class="article-expand">
          <div class="card-expand-body">{card_paragraphs}</div>
          <button class="collapse-btn" onclick="collapseThis(this)">Close &uarr;</button>
        </div>
      </div>"""

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
  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-GZ5F591SL0"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-GZ5F591SL0');
  </script>
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
        <button class="cat-btn" data-cat="sports">Sports</button>
      </nav>
      <div class="header-actions">
        <button class="theme-toggle" id="themeToggle" aria-label="Toggle theme">&#9790;</button>
        <button class="support-btn" onclick="window.open('https://buymeacoffee.com/andrewdobrow','_blank')">Support Plain</button>
      </div>
    </div>
  </header>

  <div class="update-bar">
    Updated at <strong>{timestamp}</strong> &mdash; Next update in <strong id="countdown">57 min</strong>
  </div>

  <main>
    {heroes_html}

    <p class="section-label">Latest</p>

    <div class="articles-grid" id="articlesGrid">
      {cards_html}
    </div>

    <div class="support-box" id="support">
      <div class="support-box-text">
        <p>Plain is free to read. No ads. No agenda.</p>
        <span>If it is worth something to you, a small contribution keeps it running.</span>
      </div>
      <button class="support-box-btn" onclick="window.open('https://buymeacoffee.com/andrewdobrow','_blank')">Support Plain &#9829;</button>
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


# -- UTILITIES --

def slug(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80]


# -- MAIN --

def main():
    timestamp     = now_et()
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
        except Exception as e:
            print(f"  Claude error for {cat_config['label']}: {e}")
            continue

    if not all_categories:
        print("No categories generated. Aborting.")
        return

    index_html = render_index(all_categories)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"\nDone. {len(all_categories)} categories written to index.html.")


if __name__ == "__main__":
    main()
