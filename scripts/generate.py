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
            "https://www.theverge.com/rss/index.xml",
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
    "entertainment": {
        "label": "Entertainment",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-US&gl=US&ceid=US:en",
            "https://variety.com/feed/",
            "https://www.rollingstone.com/feed/",
            "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
        ],
    },
    "politics": {
        "label": "Politics",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/POLITICS?hl=en-US&gl=US&ceid=US:en",
            "https://rss.politico.com/politics-news.xml",
            "https://thehill.com/feed/",
            "https://feeds.npr.org/1014/rss.xml",
        ],
    },
    "health": {
        "label": "Health",
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.bbci.co.uk/news/health/rss.xml",
            "https://www.statnews.com/feed/",
        ],
    },
}

HEADLINES_PER_CATEGORY = 12

GUARDIAN_API_KEY = os.environ.get("GUARDIAN_API_KEY", "")

# Direct publisher RSS feeds used as content bank — richer summaries than Google News
CONTENT_BANK_FEEDS = [
    # BBC
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/us-and-canada/rss.xml",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    # NPR
    "https://feeds.npr.org/1001/rss.xml",
    "https://feeds.npr.org/1004/rss.xml",
    # The Guardian
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/us-news/rss",
    "https://www.theguardian.com/business/rss",
    "https://www.theguardian.com/technology/rss",
    "https://www.theguardian.com/science/rss",
    "https://www.theguardian.com/sport/rss",
    "https://www.theguardian.com/culture/rss",
    # ESPN
    "https://www.espn.com/espn/rss/news",
    # TechCrunch / Ars / Verge
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
]

# Feeds that reliably include images in RSS — used for image matching
IMAGE_BANK_FEEDS = [
    # BBC (all sections)
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/us-and-canada/rss.xml",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://feeds.bbci.co.uk/sport/american-football/rss.xml",
    # The Guardian
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/us-news/rss",
    "https://www.theguardian.com/business/rss",
    "https://www.theguardian.com/technology/rss",
    "https://www.theguardian.com/science/rss",
    "https://www.theguardian.com/sport/rss",
    # NPR
    "https://feeds.npr.org/1001/rss.xml",
    "https://feeds.npr.org/1004/rss.xml",
    "https://feeds.npr.org/1006/rss.xml",
    # Sports
    "https://www.espn.com/espn/rss/news",
    "https://www.cbssports.com/rss/headlines",
    "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
    # Tech
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    # Entertainment
    "https://variety.com/feed/",
    "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    # Yahoo News (broad aggregator with images)
    "https://news.yahoo.com/rss",
]
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


def upscale_image_url(url):
    """Upscale BBC CDN images by replacing size param with 1024."""
    if not url or "ichef.bbci.co.uk" not in url:
        return url
    return re.sub(r"/\d{2,3}/", "/1024/", url, count=1)


def build_image_bank():
    """Fetch images from RSS feeds that reliably include them (BBC, ESPN, TechCrunch)."""
    bank = []
    for url in IMAGE_BANK_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "").strip()
                img   = extract_image(entry)
                if title and img:
                    bank.append({"title": title, "image_url": img, "source": url})
        except Exception as e:
            print(f"  Image bank feed error ({url[:50]}): {e}")
    print(f"  Image bank built: {len(bank)} entries with images")
    return bank


def match_image(headline, image_bank, cat_key=""):
    """Fuzzy-match a headline against the image bank."""
    stops = {"that","this","with","from","have","been","after","over","into","says","said","will","than","more","also","when","were","they","their","about"}
    def tokens(text):
        return set(w.lower().strip(".,;:()") for w in text.split() if len(w) > 3 and w.lower() not in stops)
    hw = tokens(headline)
    best_score, best_img = 0, ""
    for entry in image_bank:
        overlap = len(hw & tokens(entry["title"]))
        if overlap > best_score and overlap >= 2:
            best_score = overlap
            best_img   = upscale_image_url(entry["image_url"])
    return best_img


def find_image(headline, entries):
    """Match headline back to RSS entry for image, link, and publish time."""
    h = headline.lower()[:50]
    for entry in entries:
        t = entry.get("title", "").lower()[:50]
        if h in t or t in h:
            return {
                "image_url": entry.get("image_url", ""),
                "link":      entry.get("link", ""),
                "published": entry.get("published", ""),
            }
    return {"image_url": "", "link": "", "published": ""}


def extract_publisher_url(entry):
    """Extract actual publisher URL from a Google News RSS entry.
    Google News embeds the publisher URL as an href in the description HTML.
    Falls back to entry link for non-Google feeds.
    """
    link = entry.get("link", "")
    if "news.google.com" not in link:
        return link  # Already a direct publisher URL
    desc = entry.get("summary", entry.get("description", ""))
    if isinstance(desc, list):
        desc = desc[0].get("value", "") if desc else ""
    matches = re.findall(r'href="(https?://(?!news\.google)[^"]+)"', desc)
    if matches:
        return matches[0]
    return link


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
                    "summary":   entry.get("summary", entry.get("description", ""))[:800],
                    "link":      extract_publisher_url(entry),
                    "image_url": extract_image(entry),
                    "published": entry.get("published", ""),
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

Editorial priorities — weigh all three together:
1. CONSEQUENCE - how significantly does this affect people or the world? A major death, cabinet resignation, market crash, or geopolitical crisis can all score equally high. Do not automatically rank policy above personal events.
2. RECENCY - fresh breaking news ranks above older stories generating follow-ups. Use judgment: an edited timestamp does not make a two-day-old story breaking news.
3. SCOPE - how many people are meaningfully affected.

Scoring guidance:
- Government/cabinet/national security changes: 8-10
- Major deaths of public figures: 8-10 on day of occurrence
- Active military or geopolitical crises: 8-9
- Major economic policy decisions: 7-9
- Natural disasters with confirmed casualties: 7-9
- Sports and entertainment: score on genuine cultural impact — a historic death or championship can score 8+, routine sports news 4-6
- Follow-up stories on previous day's events (new details, minor updates): 4-6, always below genuinely new stories of similar weight
- Caution: RSS timestamps refresh on edits — judge whether a story is genuinely new before using recency as a factor.
- For the Politics category: strongly prioritize US political news (Congress, White House, Supreme Court, federal agencies, elections). International political stories should only score above 6 if they have direct major implications for the US or represent extraordinary global significance. A government reshuffle in a small or mid-size country should never outscore US political developments.
- For the U.S. category: political news should only score above 7 if it has broad non-political consequences — meaning it directly affects the economy, public safety, constitutional rights, or national security. Routine congressional procedural news, political appointments, campaign developments, and party dynamics belong in Politics, not U.S. The U.S. category should serve readers who want national news without a political focus.

CRITICAL ACCURACY RULES - never violate these:
- Only write details explicitly stated in the provided headlines and summaries.
- Never speculate, infer, or invent causes, circumstances, or details not in the source.
- If a detail is not in the source, omit it. Never write any sentence that describes missing, unavailable,
  unconfirmed, unreleased, or unknown information — in any phrasing whatsoever.
- This means never writing sentences like: "details have not been released", "circumstances are unknown",
  "officials have not commented", "no cause has been given", "it is unclear why", "the reason is not known",
  or ANY variation of this pattern. If you do not have a fact, do not mention it in any form.
- Never fabricate quotes, statistics, names, or events not present in the source material.
- Write what is confirmed. Stop when the confirmed facts run out.

TEMPORAL ACCURACY RULES - always apply these:
- Pay close attention to when events occurred. Use past tense for events that have already happened.
- If a headline provides new context or details about a previous event (e.g. "details emerge about yesterday's death"), frame the article as an update: "New details have emerged about..." or "Following [person]'s death on [day]..." — not as a new event happening now.
- If a story references something that happened "yesterday" or on a prior date, make that timing clear in the article. Never write about a past event as if it is currently unfolding.
- The article should reflect the current state of the story, not just the most dramatic moment.

Avoid: sensationalism, outrage bait, celebrity news.
Write in plain direct English. No jargon. No padding. No em dashes.
NEVER editorialize or characterize. Do not use loaded language, emotional framing, or
value judgments. Words like "controversial", "rocky", "embattled", "slammed", "blasted",
"marginalized", "chaotic", "failed" are editorial opinions — never use them.
Report what happened. Let readers draw their own conclusions."""


def strip_markdown(text, headline=""):
    """Remove markdown formatting and headline restatements from article text."""
    if not text:
        return text
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Remove common Guardian/newsletter openers
    greetings = ["good morning.", "good afternoon.", "good evening.", "good morning,", "good afternoon,", "good evening,"]
    lower = text.lower()
    for g in greetings:
        if lower.startswith(g):
            text = text[len(g):].lstrip()
            break

    # Remove first paragraph if it looks like a headline restatement
    if headline:
        paragraphs = text.split("\n\n")
        if paragraphs:
            first = paragraphs[0].strip()
            if len(first.split()) < 20:
                hl_words = set(re.sub(r"[^a-z0-9 ]", " ", headline.lower()).split())
                p_words  = set(re.sub(r"[^a-z0-9 ]", " ", first.lower()).split())
                if len(hl_words & p_words) >= min(4, len(hl_words) // 2):
                    text = "\n\n".join(paragraphs[1:]).strip()
    return text


def generate_category_content(category_key, category_label, headlines):
    # Build headlines with raw published strings for Claude to copy back
    def hl_line(i, h):
        pub = h.get("published", "")
        pub_str = f" [pub:{pub}]" if pub else ""
        return f"{i+1}. {h['title']}{pub_str}\n   {h['summary'][:600]}"
    headlines_text = "\n".join(hl_line(i, h) for i, h in enumerate(headlines))

    prompt = f"""Here are the current top headlines for the {category_label} category:

{headlines_text}

Tasks:
1. Identify the single most important/urgent story.
2. Write a headline that accurately reflects the current state of the story. If the story is an update to a previous event, the headline should reflect that (e.g. "New Details Emerge in Kyle Busch Death" or "Kyle Busch Found Unresponsive Before Death"). Never write a headline that makes a past event sound like it is happening now.
3. Write a 420-480 word factual article for the hero position.
4. For the next {CARDS_PER_CATEGORY} most important stories write:
   - teaser: one sentence card preview
   - body: two short paragraphs (~120 words) expanding on the story
   - urgency_score: integer 1-10 using the same criteria as the hero

Return ONLY valid JSON:
{{
  "hero": {{
    "headline": "accurate temporally-framed headline",
    "body": "full article text with paragraph breaks",
    "urgency_score": <1-10>,
    "published": "copy the [pub:...] string from the chosen headline exactly, including the date",
    "source_index": <the number of the chosen headline, e.g. 3>
  }},
  "cards": [
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>, "published": "copy timestamp", "source_index": <number>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>, "published": "copy timestamp", "source_index": <number>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>, "published": "copy timestamp", "source_index": <number>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>, "published": "copy timestamp", "source_index": <number>}},
    {{"headline": "...", "teaser": "...", "body": "two paragraphs...", "urgency_score": <1-10>, "published": "copy timestamp", "source_index": <number>}}
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

    # Use source_index to attach original RSS link and image directly — no fuzzy matching needed
    def attach_source(item, headlines):
        idx = item.get("source_index")
        if idx is not None:
            try:
                source = headlines[int(idx) - 1]
                item["link"]      = source.get("link", "")
                item["image_url"] = source.get("image_url", "")
            except (IndexError, ValueError, TypeError):
                item["link"]      = ""
                item["image_url"] = ""
        else:
            item["link"]      = ""
            item["image_url"] = ""

        # Format published
        raw_pub = item.get("published", "").replace("pub:", "").strip().strip("[]")
        item["published"] = format_age(raw_pub)
        return item

    data["hero"] = attach_source(data["hero"], headlines)
    data["hero"]["body"] = strip_markdown(data["hero"].get("body", ""), data["hero"].get("headline", ""))
    for card in data.get("cards", []):
        attach_source(card, headlines)
        card["body"] = strip_markdown(card.get("body", ""), card.get("headline", ""))

    # Age-based score decay for stale non-breaking stories
    def decay_score(item):
        score = item.get("urgency_score", 5)
        idx = item.get("source_index")
        if idx is None: return item
        try:
            pub_raw = headlines[int(idx) - 1].get("published", "")
            if not pub_raw: return item
            from email.utils import parsedate_to_datetime
            from datetime import timezone
            dt  = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
            now = datetime.now(timezone.utc)
            hrs = (now - dt).total_seconds() / 3600
            headline = item.get("headline", "").lower()
            fresh_words = ["confirms","confirmed","announces","announced","reveals","charges",
                          "arrested","resigns","fired","dies","dead","breaks","exclusive","new details"]
            is_fresh = any(w in headline for w in fresh_words)
            if not is_fresh:
                if hrs > 48: score = min(score, 4)
                elif hrs > 24: score = min(score, 6)
        except Exception:
            pass
        item["urgency_score"] = score
        return item

    decay_score(data["hero"])
    for card in data.get("cards", []): decay_score(card)

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


def build_content_bank():
    """Build a bank of rich publisher content from direct RSS feeds.
    These have far richer summaries than Google News and no redirect issues.
    """
    bank = []
    seen = set()
    for url in CONTENT_BANK_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:25]:
                title = entry.get("title", "").strip()
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                summary = entry.get("summary", entry.get("description", ""))[:1200]
                if summary and len(summary) > 100:
                    bank.append({
                        "title":   title,
                        "summary": summary,
                        "source":  feed.feed.get("title", url),
                    })
        except Exception as e:
            print(f"  Content bank feed error ({url[:50]}): {e}")
    print(f"  Content bank built: {len(bank)} entries")
    return bank


def find_content(headline, content_bank, max_entries=5):
    """Fuzzy-match a headline against the content bank and return combined rich summaries."""
    stops = {"that","this","with","from","have","been","said","will","more",
             "also","when","were","they","their","about","says","just","after"}
    def tokens(text):
        return set(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()) - stops
    hero_tokens = tokens(headline)
    matches = []
    for entry in content_bank:
        overlap = len(hero_tokens & tokens(entry["title"]))
        if overlap >= 2:
            matches.append((overlap, entry))
    matches.sort(key=lambda x: x[0], reverse=True)
    if not matches:
        return ""
    parts = []
    for _, entry in matches[:max_entries]:
        src     = entry["source"]
        title   = entry["title"]
        summary = entry["summary"]
        parts.append(f"[{src}] {title}\n{summary}")
    return "\n\n".join(parts)


def fetch_guardian_article(headline):
    """Search Guardian API for matching article and return full body text.
    Free API key returns complete article content.
    """
    if not GUARDIAN_API_KEY:
        return ""
    try:
        import requests as _req
        # Build search query from key headline words
        stops = {"that","this","with","from","have","been","said","will","more",
                 "also","when","were","they","their","about","says","just","after","as","a","the","in","of","for","to","and","or","on","at","an"}
        words = [w for w in re.sub(r"[^a-z0-9 ]", " ", headline.lower()).split()
                 if len(w) > 3 and w not in stops][:6]
        query = " ".join(words)
        params = {
            "q":            query,
            "api-key":      GUARDIAN_API_KEY,
            "show-fields":  "bodyText",
            "page-size":    3,
            "order-by":     "relevance",
        }
        resp = _req.get("https://content.guardianapis.com/search", params=params, timeout=8)
        results = resp.json().get("response", {}).get("results", [])
        for result in results:
            body = result.get("fields", {}).get("bodyText", "")
            if body and len(body.split()) > 150:
                words_list = body.split()
                truncated  = " ".join(words_list[:900])
                print(f"  Guardian: {len(words_list)} words fetched")
                return truncated
    except Exception as e:
        print(f"  Guardian fetch failed: {e}")
    return ""


def fetch_article_text(url, max_words=900):
    """Article fetch disabled — base articles from RSS summaries only."""
    return ""



def enhance_hero_article(hero, full_text):
    """Rewrite the hero article using the full source text for accuracy and detail."""
    if not full_text or len(full_text.split()) < 150:
        return hero  # Not enough text to improve on
    body = hero.get("body", "")
    prompt = (
        f"You wrote this article about: {hero.get('headline', '')}\n\n"
        f"Here is source material:\n\n{full_text}\n\n"
        "If the source material is clearly about a different story or topic than your article, "
        "return your original article exactly as written with no changes. "
        "Otherwise, rewrite your article using confirmed facts from the source. "
        "Write in your own words — do not copy sentences or phrases verbatim from the source. "
        "You may reference specific quotes from named individuals if they appear in the source, "
        "but paraphrase everything else in plain clear English. "
        "Do not invent details not in the source. Do not comment on absent information. "
        "Do not copy newsletter openers like 'Good morning' or any introductory salutation. "
        "CRITICAL: If the source material describes a different location, person, or incident than "
        "the headline, return your original article exactly as written with no changes. "
        "Never invent details to make a mismatched source fit the headline. "
        "Keep it 420-480 words. Plain direct English. No em dashes."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        enhanced = resp.content[0].text.strip()
        if enhanced:
            hero["body"] = strip_markdown(enhanced, hero.get("headline", ""))
            print(f"  Hero article enhanced with full source text")
    except Exception as e:
        print(f"  Enhancement failed ({e}), keeping original")
    return hero


def format_age(published_str):
    """Format publish time using stdlib only — no pytz needed."""
    if not published_str:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        from datetime import timezone, timedelta
        et      = timezone(timedelta(hours=-4))  # EDT approximation
        dt_utc  = parsedate_to_datetime(published_str).astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        mins    = int((now_utc - dt_utc).total_seconds() / 60)
        dt_et   = dt_utc.astimezone(et)
        now_et  = now_utc.astimezone(et)
        hour    = dt_et.hour % 12 or 12
        ampm    = "AM" if dt_et.hour < 12 else "PM"
        time_str = f"{hour}:{dt_et.strftime('%M')} {ampm} ET"
        if mins < 60:
            return "A few minutes ago"
        if dt_et.date() == now_et.date():
            return time_str
        if mins < 2880:
            return f"Yesterday, {time_str}"
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        return f"{months[dt_et.month-1]} {dt_et.day}, {time_str}"
    except Exception:
        return ""


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
        "PRIMARY signal: consequence and substance of the story itself.\n"
        "SECONDARY signal: recency — but use it carefully. RSS timestamps update when articles are edited, so a recent timestamp does not always mean a story just broke. Judge whether the story itself is genuinely new or just an update to an older event.\n"
        "Apply this weighting:\n"
        "1. Government resignations, cabinet changes, national security developments: always near the top\n"
        "2. Active geopolitical crises, major economic policy decisions: very high\n"
        "3. Genuinely new breaking stories (not follow-ups or minor updates to older events): elevated\n"
        "4. Follow-up stories (new details, context, or minor updates about a previous day's event): rank below genuinely new stories of equal or lesser importance\n"
        "5. Sports, entertainment, or personal stories: rank below policy, governance, and crisis stories unless exceptionally significant\n"
        "When two stories seem equally important, use the timestamp as a tiebreaker — but only if you are confident the story is genuinely new and not a republished update.\n\n"
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


def fetch_market_data():
    """Fetch market data server-side during pipeline run. No CORS issues."""
    import requests as _req
    symbols = [
        ("sp500",  "^GSPC",  "S&P 500"),
        ("dow",    "^DJI",   "DOW"),
        ("nasdaq", "^IXIC",  "NASDAQ"),
        ("oil",    "CL=F",   "Oil"),
    ]
    results = {}
    for key, sym, label in symbols:
        try:
            url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
            hdrs = {"User-Agent": "Mozilla/5.0"}
            resp = _req.get(url, headers=hdrs, timeout=6)
            meta = resp.json()["chart"]["result"][0]["meta"]
            price  = meta["regularMarketPrice"]
            prev   = meta.get("previousClose") or meta.get("chartPreviousClose", price)
            change = (price - prev) / prev * 100
            state  = meta.get("marketState", "CLOSED")
            results[key] = {
                "label":  label,
                "price":  f"{price:,.2f}",
                "change": f"{change:+.2f}",
                "up":     change >= 0,
                "live":   state == "REGULAR",
            }
        except Exception as e:
            print(f"  Market fetch failed ({sym}): {e}")
            results[key] = None
    live = any(v and v["live"] for v in results.values())
    print(f"  Market data: {sum(1 for v in results.values() if v)} symbols fetched, market {'live' if live else 'closed'}")
    return results, live


def render_index(all_categories, market_data=None, market_live=False):
    timestamp = now_et()
    top_cat   = max(all_categories, key=lambda c: c["hero"].get("urgency_score", 0))
    hero_desc = top_cat["hero"].get("headline", "News without the noise")[:120]

    # Build market ticker HTML from server-side data
    def fmt_ticker(key, label):
        d = (market_data or {}).get(key)
        if not d:
            return f'<span class="ticker-item">{label} <span class="ticker-val">--</span></span>'
        cls  = "ticker-up" if d["up"] else "ticker-down"
        return f'<span class="ticker-item">{label} <span class="ticker-val">{d["price"]} <span class="{cls}">{d["change"]}%</span></span></span>'
    ticker_html = " ".join([
        fmt_ticker("sp500",  "S&amp;P 500"),
        fmt_ticker("dow",    "DOW"),
        fmt_ticker("nasdaq", "NASDAQ"),
        fmt_ticker("oil",    "Oil"),
    ])
    closed_html = '' if market_live else '<span class="ticker-closed">Market closed</span>'

    # -- Hero sections (one per category + "all") --
    def hero_section(cat_key, cat_label, hero, visible):
        display    = "" if visible else ' style="display:none"'
        fade       = " fade-in" if visible else ""
        preview    = hero["body"][:380].rstrip()
        paragraphs = make_paragraphs(hero["body"])
        img_url    = hero.get("image_url", "")
        img_html   = f'<img class="hero-image" src="{img_url}" alt="{hero["headline"]}" loading="lazy">' if img_url else ""
        pub_time   = hero.get("published") or f"Today, {timestamp}"
        return f"""
    <section class="hero{fade}" data-cat-hero="{cat_key}"{display}>
      <div class="hero-inner">
        {img_html}
        <span class="tag">{cat_label}</span>
        <h1>{hero["headline"]}</h1>
        <p class="hero-summary">{preview}...</p>
        <div class="hero-foot">
          <span class="meta">{pub_time}</span>
          <button class="expand-btn" onclick="toggleExpand(this)">Continue reading &darr;</button>
        </div>
        <div class="article-expand hero-expand">
          <div class="hero-expand-body">{paragraphs}</div>
          <button class="collapse-btn" onclick="collapseThis(this)">Close &uarr;</button>
        </div>
      </div>
    </section>"""

    heroes_html  = hero_section("all", top_cat["category_label"], top_cat["hero"], visible=True)
    for cat in all_categories:
        heroes_html += hero_section(cat["category_key"], cat["category_label"], cat["hero"], visible=False)

    # -- Card grid -- category heroes + regular cards, sorted by urgency --
    all_cards = []
    top_cat_key = top_cat["category_key"]

    # Add category heroes to pool — skip top_cat (already shown as the All hero above)
    for cat in all_categories:
        if cat["category_key"] == top_cat_key:
            continue
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

    # Static support card injected at position 3
    support_card = """
      <div class="article-card support-card fade-in" data-cat="all" data-support-card="true">
        <span class="card-tag support-card-tag">Plain</span>
        <h2 class="card-headline support-card-headline">Plain is free. Help keep it that way.</h2>
        <p class="card-summary">No ads. No paywalls. No agenda. Plain runs entirely on reader support. If it's worth something to you, consider buying us a coffee.</p>
        <div class="card-foot">
          <a href="https://buymeacoffee.com/andrewdobrow" target="_blank" class="support-card-btn">Support Plain &#9829;</a>
        </div>
      </div>"""

    cards_html = ""
    for i, card in enumerate(all_cards):
        if i == 2:
            cards_html += support_card
        teaser = card.get("teaser", card.get("summary", ""))
        body   = card.get("body", card.get("summary", ""))
        card_paragraphs = make_paragraphs(body)
        ck        = card["cat_key"]
        cl        = card["cat_label"]
        card_time = card.get("published") or timestamp
        is_hero_attr = ' data-is-hero="true"' if card.get("is_hero") else ""
        cards_html += f"""
      <div class="article-card fade-in" data-cat="{ck}"{is_hero_attr}>
        <span class="card-tag">{cl}</span>
        <h2 class="card-headline">{card["headline"]}</h2>
        <p class="card-summary">{teaser}</p>
        <div class="card-foot">
          <span class="card-time">{card_time}</span>
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
  <meta name="description" content="Plain: {hero_desc} — Updated every hour. No ads. No agenda. Always free.">
  <!-- Open Graph -->
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://plainnews.app">
  <meta property="og:title" content="Plain — News without the noise">
  <meta property="og:description" content="Updated every hour. No ads. No paywalls. No agenda. Just the news that matters.">
  <meta property="og:image" content="https://plainnews.app/social-card.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Plain — News without the noise">
  <meta name="twitter:description" content="Updated every hour. No ads. No paywalls. No agenda. Just the news that matters.">
  <meta name="twitter:image" content="https://plainnews.app/social-card.png">
  <link rel="stylesheet" href="style.css?v={datetime.utcnow().strftime('%Y%m%d%H')}">
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
        <button class="cat-btn" data-cat="politics">Politics</button>
        <button class="cat-btn" data-cat="business">Business</button>
        <button class="cat-btn" data-cat="tech">Tech</button>
        <button class="cat-btn" data-cat="science">Science</button>
        <button class="cat-btn" data-cat="health">Health</button>
        <button class="cat-btn" data-cat="sports">Sports</button>
        <button class="cat-btn" data-cat="entertainment">Entertainment</button>
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

  <div class="market-ticker">
    <div class="ticker-inner">
      <span class="ticker-label">Markets</span>
      {ticker_html}
      {closed_html}
    </div>
  </div>

  <main>
    {heroes_html}

    <p class="section-label">Latest</p>

    <div class="articles-grid" id="articlesGrid">
      {cards_html}
    </div>

    <div class="support-box" id="support">
      <div class="support-box-text">
        <p>Plain runs on reader support.</p>
        <span>No ads. No investors. No agenda. Just a belief that clean news should be free and a real cost to keep it that way. If Plain is part of your day, consider buying us a coffee.</span>
      </div>
      <button class="support-box-btn" onclick="window.open('https://buymeacoffee.com/andrewdobrow','_blank')">Support Plain &#9829;</button>
    </div>
  </main>

  <footer>
    <div class="footer-inner">
      <span class="footer-wordmark">plain</span>
      <span class="footer-tagline">Updated every hour. No ads. No noise. Always free.</span>
      <div class="footer-links">
        <a href="about.html">About</a>
        <a href="https://buymeacoffee.com/andrewdobrow" target="_blank">Support</a>
        <a href="mailto:anjrued123@gmail.com">Contact</a>
        <a href="https://lowsignal.dev" target="_blank">Built by Low Signal Labs</a>
      </div>
    </div>
  </footer>

  <script src="main.js?v={datetime.utcnow().strftime('%Y%m%d%H')}"></script>
</body>
</html>"""



# -- MAIN --

def main():
    all_categories = []

    # Build image bank and content bank once per run
    print("Building image bank...")
    image_bank = build_image_bank()
    print("Building content bank...")
    content_bank = build_content_bank()

    for cat_key, cat_config in CATEGORIES.items():
        print(f"Processing: {cat_config['label']}...")
        headlines = fetch_headlines(cat_config["feeds"])
        if not headlines:
            print(f"  No headlines found for {cat_config['label']}, skipping.")
            continue
        try:
            data = generate_category_content(cat_key, cat_config["label"], headlines)

            # Images — source_index already attached image_url, fall back to image bank
            img = data["hero"].get("image_url") or match_image(data["hero"]["headline"], image_bank, cat_key)
            data["hero"]["image_url"] = img

            # Hero enrichment — combine all available sources
            hero_headline = data["hero"]["headline"]

            # 1. Guardian API — full article text (best source when available)
            guardian_text = fetch_guardian_article(hero_headline)

            # 2. Content bank — rich publisher summaries from BBC, NPR, Guardian RSS etc
            bank_content  = find_content(hero_headline, content_bank)

            # 3. Related RSS summaries from the category feed
            hero_idx     = data["hero"].get("source_index", 1) - 1
            related_parts = []
            hero_tokens   = set(re.sub(r"[^a-z0-9 ]", " ", hero_headline.lower()).split())
            stops         = {"that","this","with","from","have","been","said","will","more",
                             "also","when","were","they","their","about","says","just"}
            hero_tokens  -= stops
            for h in headlines:
                h_tokens = set(re.sub(r"[^a-z0-9 ]", " ", h.get("title","").lower()).split()) - stops
                if len(hero_tokens & h_tokens) >= 2:
                    related_parts.append(h.get("title","") + ". " + h.get("summary",""))
            related_text = " | ".join(related_parts[:6])

            # Combine: Guardian full text first, then bank content, then related summaries
            source_parts = [p for p in [guardian_text, bank_content, related_text] if p]
            source_text  = "\n\n".join(source_parts)

            if source_text and len(source_text.split()) >= 100:
                # Final relevance check — ensure source actually relates to hero headline
                stops2 = {"the","a","an","in","of","for","to","and","or","on","at","is","was","are","were","that","this","with"}
                hl_tok = set(re.sub(r"[^a-z0-9 ]", " ", hero_headline.lower()).split()) - stops2
                src_tok = set(re.sub(r"[^a-z0-9 ]", " ", source_text[:500].lower()).split()) - stops2
                # Geographic mismatch check — key country/place names must not conflict
                geo_words = {"china","chinese","russia","russian","ukraine","ukrainian","iran","israeli","israel",
                             "australia","australian","india","indian","france","french","germany","german",
                             "britain","british","uk","japan","japanese","brazil","mexican","mexico",
                             "congo","ebola","africa","african","europe","european","california","texas",
                             "florida","washington","london","paris","beijing","moscow","gaza",
                             "maralago","capitol","pentagon","whitehouse","nasa","nascar","senate","congress"}
                hl_geo  = hl_tok & geo_words
                src_geo = src_tok & geo_words
                geo_conflict = bool(hl_geo) and bool(src_geo) and not (hl_geo & src_geo)
                if geo_conflict:
                    print(f"  Enhancement skipped: geographic mismatch ({hl_geo} vs {src_geo})")
                elif len(hl_tok & src_tok) >= 3:
                    data["hero"] = enhance_hero_article(data["hero"], source_text)
                    print(f"  Enhanced with: {'Guardian+' if guardian_text else ''}{'bank+' if bank_content else ''}{'related' if related_text else ''}")
                else:
                    print(f"  Enhancement skipped: insufficient keyword overlap")

            all_categories.append(data)
            print(f"  Hero: {data['hero']['headline'][:60]}... (urgency: {data['hero'].get('urgency_score')}, image: {'yes' if img else 'no'})")
        except Exception as e:
            print(f"  Claude error for {cat_config['label']}: {e}")
            continue

    if not all_categories:
        print("No categories generated. Aborting.")
        return

    print("Fetching market data...")
    market_data, market_live = fetch_market_data()

    index_html = render_index(all_categories, market_data, market_live)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    print(f"\nDone. {len(all_categories)} categories written to index.html.")


if __name__ == "__main__":
    main()
