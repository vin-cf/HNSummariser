from datetime import datetime
import requests
import re
import time
from newspaper import Article
import trafilatura

def get_top_story_ids(limit=5):
    top_ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json").json()
    print(f"Top story IDs fetched: {top_ids[:limit]}")
    return top_ids[:limit]


def get_story_with_comments(story_id, comment_limit=10):
    story = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json").json()

    # Get top-level comment IDs
    comment_ids = story.get('kids', [])[:comment_limit]
    comments = []

    for cid in comment_ids:
        comment = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{cid}.json").json()
        if comment and comment.get('text'):
            comments.append(comment['text'])
            print(f"Fetched {comment['text'][:720]}... for comment ID {cid}")
    return {
        'title': story.get('title'),
        'url': story.get('url'),
        'comments': comments
    }


def summarize_comments(comments):
    comments_text = "\n\n".join(comments[:10])  # Avoid token overflow
    prompt = f"""
    You are an expert summarizer analyzing a Hacker News comment thread.

    Based on the following user comments:
    {comments_text}

    Your task is to:
    0. Summarise the article
    1. Identify the **overall sentiment** (e.g. positive, negative, mixed, neutral) — based on tone and consensus.
    2. Extract and clearly summarize the **top viewpoints or arguments** from users. Group similar perspectives where relevant.
    3. Highlight any **notable debates, disagreements, or unexpected insights** that emerged.

    Write in a concise, informative tone suitable for narration in a tech news podcast.
    Avoid quoting usernames or raw HTML. Be objective, structured, and podcast-friendly.
    """

    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "llama3.1",
        "prompt": prompt,
        "stream": False  # Set to True if you want streaming responses
    }
    print(f"Summarising {comments_text[:50]}...")
    response = requests.post(url, json=payload)
    response.raise_for_status()

    return response.json()["response"]


# def summarise_article_contents(url: str):
#     try:
#         article = Article(url)
#         article.download()
#         article.parse()
#         return article.text
#     except Exception as e:
#         print(f"Failed to fetch article: {e}")
#         return None



# -----------------------------
# Step 1: Archive link extraction
# -----------------------------

def extract_archive_url_from_comments(comments: list[str]):
    archive_pattern = r'https?://(archive\.(is|ph|today|md))/[^\s<>"\']+'
    for comment in comments:
        match = re.search(archive_pattern, comment)
        if match:
            print(f"Found archive link: {match.group(0)}")
            return match.group(0)
    return None


# -----------------------------
# Step 2: Article content extraction with retry and fallback
# -----------------------------

def fetch_article_text(url, retries=3, delay=2):
    for attempt in range(retries):
        try:
            article = Article(url)
            article.download()
            article.parse()
            if article.text and len(article.text.split()) > 100:
                return article.text
        except Exception as e:
            print(f"[Attempt {attempt + 1}] Failed to fetch article from {url}: {e}")
            time.sleep(delay)

    # Fallback to trafilatura if newspaper3k fails
    for attempt in range(retries):
        print(f"Trying trafilatura fallback for: {url}")
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            return trafilatura.extract(resp.text)
        print(f"trafilatura failed with error code {resp.status_code}: {resp.reason}")
    return None


# -----------------------------
# Step 3: Detect possible paywalls
# -----------------------------

def is_likely_paywalled(text):
    if not text or len(text.split()) < 100:
        return True
    keywords = ['subscribe', 'sign in to read', 'already a subscriber', 'register to continue']
    return any(k in text.lower() for k in keywords)


# -----------------------------
# Step 4: Unified content loader with fallback to archive
# -----------------------------

def fetch_article_with_fallback(url: str, comments: list[str]):
    print(f"🔍 Fetching original article: {url}")
    text = fetch_article_text(url)

    if text and not is_likely_paywalled(text):
        return text

    print("⚠️ Detected possible paywall or empty content. Checking comments for archive link...")
    archive_url = extract_archive_url_from_comments(comments)

    if archive_url:
        print(f"🔁 Trying archive link: {archive_url}")
        text = fetch_article_text(archive_url)
        if text:
            return text

    print("❌ Failed to fetch article from both original and archive.")
    return None


def save_summary_to_file(story, summary, output_dir="."):
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
    filename = f"{output_dir}/hn_summary_{timestamp}.txt"

    # Build content
    content = (
        f"Title: {story['title']}\n"
        f"URL: {story['url']}\n"
        f"Summary: {summary}\n"
    )

    # Write to file
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ Summary saved to {filename}")


if __name__ == "__main__":
    top_story_ids = get_top_story_ids(limit=5)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
    for story_id in top_story_ids:
        story = get_story_with_comments(story_id, comment_limit=10)
        if story['comments']:
            summary = summarize_comments(story['comments'])
            url = story['url']
            # url = 'https://www.wsj.com/economy/central-banking/federal-reserve-building-renovation-d7d25ddc'
            article_contents = fetch_article_with_fallback(url, story['comments'])
            # article_contents = fetch_article_with_fallback(url, ['https://archive.today/qfh7g'])
            filename = f"./hn_summary_{timestamp}.txt"
            content = (
                f"Title: {story['title']}\n"
                f"URL: {story['url']}\n"
                f"Summary: {summary}\n"
            )
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"✅ Summary saved to {filename}")
        else:
            print(f"No comments found for story ID {story_id}\n")
