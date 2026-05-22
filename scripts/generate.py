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

def extract_image(entry):
    """Try every known location for an image in an RSS entry."""
    def valid(u):
        if not u or len(u) < 15: return False
        return not any(x in u.lower() for x in ["1x1", "pixel", "spacer", "tracking", "data:"])

    # 1. media:thumbnail (BBC, many feeds)
    for t in (getattr(entry, "media_thumbnail", None) or []):
        if isinstance(t, dict) and valid(t.get("url", "")):
            return t["url"]

    # 2. media:content
    for m in (getattr(entry, "media_content", None) or []):
        if not isinstance(m, dict): continue
        u = m.get("url", "")
        if valid(u) and ("image" in m.get("type", "") or any(u.lower().endswith(e) for e in (".jpg",".jpeg",".png",".webp"))):
            return u

    # 3. enclosures
    for enc in (getattr(entry, "enclosures", None) or []):
        if isinstance(enc, dict) and "image" in enc.get("type", ""):
            u = enc.get("href", enc.get("url", ""))
            if valid(u): return u

    # 4. Parse <img> from description HTML (catches Google News thumbnails)
    html = ""
    for field in ["description", "summary"]:
        val = entry.get(field, "") or getattr(entry, field, "")
        if isinstance(val, list) and val:
            html = val[0].get("value", "") if isinstance(val[0], dict) else str(val[0])
        elif isinstance(val, str):
            html = val
        if html: break

    for match in re.finditer(r'<img[^>]+src=["\']([^"\']{20,})["\']', html):
        u = match.group(1)
        if valid(u): return u

    return ""


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def decode_google_news_url(url):
    """Decode a Google News RSS article URL to get the actual publisher URL.
    The article ID is base64-encoded and contains the source URL embedded in it.
    """
    import base64
    try:
        for sep in ["/rss/articles/", "/articles/"]:
            if sep in url:
                article_id = url.split(sep)[1].split("?")[0]
                break
        else:
            return ""
        pad     = (4 - len(article_id) % 4) % 4
        decoded = base64.urlsafe_b64decode(article_id + "=" * pad)
        # The publisher URL is embedded as a UTF-8 string in the binary data
        for i in range(len(decoded) - 4):
            if decoded[i:i+4] == b"http":
                raw = decoded[i:].decode("latin-1", errors="replace")
                # URL ends at first control character or null byte
                end = len(raw)
                for j, ch in enumerate(raw):
                    if ord(ch) < 32:
                        end = j
                        break
                candidate = raw[:end].strip()
                if len(candidate) > 20 and "." in candidate and "google.com" not in candidate:
                    return candidate
    except Exception:
        pass
    return ""


def fetch_og_image(url, timeout=6):
    """Fetch og:image from a news article URL.
    For Google News URLs, decodes the article ID to get the publisher URL directly.
    """
    if not url:
        return ""
    try:
        import requests as _req
        # Resolve Google News URLs to the actual publisher URL
        actual = url
        if "google.com" in url:
            decoded = decode_google_news_url(url)
            if decoded:
                actual = decoded
                print(f"  Decoded Google URL -> {actual[:60]}")
            else:
                # Fallback: follow redirects with requests
                try:
                    r = _req.head(url, headers=BROWSER_HEADERS, allow_redirects=True, timeout=4)
                    if "google.com" not in r.url:
                        actual = r.url
                except Exception:
                    pass
        resp = _req.get(actual, headers=BROWSER_HEADERS, timeout=timeout, stream=True)
        html = b""
        for chunk in resp.iter_content(4096):
            html += chunk
            if len(html) >= 25000: break
        html = html.decode("utf-8", errors="ignore")
        # Build patterns without embedding quotes in the regex
        dq, sq = chr(34), chr(39)
        q  = "[" + dq + sq + "]"
        nq = "[^" + dq + sq + "]"
        p1 = re.compile("<meta[^>]+property=" + q + "og:image" + q + r"[^>]+content=" + q + "(" + nq + r"+)" + q, re.I)
        p2 = re.compile("<meta[^>]+content=" + q + "(" + nq + r"+)" + q + r"[^>]+property=" + q + "og:image" + q, re.I)
        for pat in (p1, p2):
            m = pat.search(html)
            if m:
                img = m.group(1).strip()
                if img.startswith("http"):
                    print(f"  Got image: {img[:60]}")
                    return img
        print(f"  No og:image found at {actual[:60]}")
    except Exception as e:
        print(f"  og:image error ({str(url)[:50]}): {e}")
    return ""


def find_image(headline, entries):
    """Match headline back to RSS entry for image and link."""
    h = headline.lower()[:50]
    for entry in entries:
        t = entry.get("title", "").lower()[:50]
        if h in t or t in h:
            return {"image_url": entry.get("image_url", ""), "link": entry.get("link", "")}
    return {"image_url": "", "link": ""}


def fetch_headlines(feeds, limit=HEADLINES_PER_CATEGORY):
    """Pull headlines from feeds in priority order. First feed fills most slots."""
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
                    "title":     title,
                    "summary":   entry.get("summary", entry.get("description", ""))[:400],
                    "link":      entry.get("link", ""),
                    "image_url": extract_image(entry),
                })
                if len(entries) >= limit:
                    break
        except Exception as e:
            print(f"  Feed error ({url[:60]}): {e}")
        if len(entries) >= limit:
            break
    return entries


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


def global_rank(all_cards):
    """Final global ranking — sends all headlines to Claude for true cross-category ordering."""
    if not all_cards:
        return all_cards
    stories = []
    for i, c in enumerate(all_cards):
        cat   = c.get("cat_label", "")
        head  = c.get("headline", "")
        stories.append(f"{i+1}. [{cat}] {head}")
    stories_text = "\n".join(stories)
    n = len(all_cards)
    prompt = (
        f"Rank these {n} news stories by true global importance and urgency.\n"
        "Most consequential stories come first regardless of category. "
        "A major World or US development beats a minor Tech story. "
        "A major Sports story (death, championship) beats a routine Business update.\n\n"
        f"{stories_text}\n\n"
        "Return ONLY a JSON array of the original numbers in ranked order, most important first.\n"
        "Example: [4, 1, 12, 7, ...]"
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        indices = json.loads(raw)
        seen, ranked = set(), []
        for idx in indices:
            i = int(idx) - 1
            if 0 <= i < n and i not in seen:
                seen.add(i)
                ranked.append(all_cards[i])
        for i, card in enumerate(all_cards):
            if i not in seen:
                ranked.append(card)
        print(f"  Global ranking: {len(ranked)} stories ordered")
        return ranked
    except Exception as e:
        print(f"  Global ranking failed ({e}), using urgency_score fallback")
        return all_cards


def render_index(all_categories):
    timestamp = now_et()
    top_cat   = max(all_categories, key=lambda c: c["hero"].get("urgency_score", 0))

    # -- Hero sections (one per category + "all") --
    def hero_section(cat_key, cat_label, hero, visible):
        display    = "" if visible else ' style="display:none"'
        fade       = " fade-in" if visible else ""
        preview    = hero["body"][:380].rstrip()
        paragraphs = make_paragraphs(hero["body"])
        img_url    = hero.get("image_url", "")
        img_html   = f'<img class="hero-image" src="{img_url}" alt="{hero["headline"]}" loading="lazy">' if img_url else ""
        wrap_class = "hero-inner hero-inner--split" if img_url else "hero-inner"
        return f"""
    <section class="hero{fade}" data-cat-hero="{cat_key}"{display}>
      <div class="{wrap_class}">
        <div class="hero-content">
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
        </div>
        {img_html}
      </div>
    </section>"""

    heroes_html  = hero_section("all", top_cat["category_label"], top_cat["hero"], visible=True)
    for cat in all_categories:
        heroes_html += hero_section(cat["category_key"], cat["category_label"], cat["hero"], visible=False)

    # -- Card grid -- category heroes + regular cards, sorted by urgency --
    all_cards = []
    top_cat_key = top_cat["category_key"]

    # Add category hero stories into the pool — they deserve to rank with everything
    for cat in all_categories:
        hero = cat["hero"]
        all_cards.append({
            "headline":      hero["headline"],
            "teaser":        hero["body"][:220].rstrip() + "...",
            "body":          hero["body"],
            "urgency_score": hero.get("urgency_score", 0),
            "image_url":     hero.get("image_url", ""),
            "cat_key":       cat["category_key"],
            "cat_label":     cat["category_label"],
            "is_hero":       True,
            # Mark the story that is also the "all" hero so we can hide it in the All grid
            "is_all_hero":   cat["category_key"] == top_cat_key,
        })

    # Add regular cards
    for cat in all_categories:
        for card in cat["cards"]:
            all_cards.append({
                **card,
                "cat_key":   cat["category_key"],
                "cat_label": cat["category_label"],
                "is_hero":   False,
            })

    all_cards.sort(key=lambda c: c.get("urgency_score", 0), reverse=True)  # Pre-sort
    all_cards = global_rank(all_cards)  # Final true global ranking

    cards_html = ""
    for card in all_cards:
        teaser = card.get("teaser", card.get("summary", ""))
        body   = card.get("body", card.get("summary", ""))
        card_paragraphs = make_paragraphs(body)
        ck       = card["cat_key"]
        cl       = card["cat_label"]
        img_url  = card.get("image_url", "")
        img_tag  = f'<img class="card-image" src="{img_url}" alt="" loading="lazy">' if img_url else ""
        is_hero_attr    = ' data-is-hero="true"' if card.get("is_hero") else ""
        is_all_hero_attr = ' data-all-hero="true"' if card.get("is_all_hero") else ""
        cards_html += f"""
      <div class="article-card fade-in" data-cat="{ck}"{is_hero_attr}{is_all_hero_attr}>
        {img_tag}
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
            # Attach images — try RSS first, fall back to og:image fetch for hero
            hero_match = find_image(data["hero"]["headline"], headlines)
            img = hero_match["image_url"]
            if not img:
                print(f"  No RSS image for hero, fetching og:image...")
                img = fetch_og_image(hero_match["link"])
            data["hero"]["image_url"] = img
            for card in data["cards"]:
                card_match = find_image(card["headline"], headlines)
                card["image_url"] = card_match["image_url"] or fetch_og_image(card_match["link"])
            all_categories.append(data)
            print(f"  Hero: {data['hero']['headline'][:60]}... (urgency: {data['hero'].get('urgency_score')}, image: {'yes' if img else 'no'})")
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
