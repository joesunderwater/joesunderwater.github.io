#!/usr/bin/env python3
"""Joe Hartmann Finds static site generator.

Reads pin metadata from pins.json and article prose from content/<id>.md,
then writes a complete static site into docs/ (GitHub Pages friendly).

Existing content files are never overwritten by this script.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["base_path"] = (cfg.get("base_path") or "").rstrip("/")
    cfg["base_url"] = (cfg.get("base_url") or "").rstrip("/")
    return cfg


def bp(cfg: dict, path: str) -> str:
    """Prefix a site-absolute path with optional GitHub Pages base_path."""
    if not path.startswith("/"):
        path = "/" + path
    return f"{cfg['base_path']}{path}"


def abs_url(cfg: dict, path: str) -> str:
    path = bp(cfg, path)
    return f"{cfg['base_url']}{path}" if cfg["base_url"] else path


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def board_slug(board: str) -> str:
    return slugify(board)


def parse_front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    meta: dict = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip().strip('"').strip("'")
    return meta, parts[2].lstrip("\n")


def md_to_html(src: str) -> str:
    """Small, dependency-free Markdown subset: headings, lists, emphasis, links, hr, paragraphs."""
    lines = src.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    in_ul = False
    para: list[str] = []

    def close_lists():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + inline(" ".join(para).strip()) + "</p>")
            para = []

    def inline(text: str) -> str:
        # Escape first, then restore simple markdown.
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
        text = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            r'<a href="\2">\1</a>',
            text,
        )
        return text

    for line in lines:
        if line.strip() == "---":
            flush_para()
            close_lists()
            out.append("<hr>")
            continue
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            flush_para()
            close_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^[-*]\s+(.+)$", line)
        if m:
            flush_para()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if not line.strip():
            flush_para()
            close_lists()
            continue
        if in_ul:
            close_lists()
        para.append(line.strip())

    flush_para()
    close_lists()
    return "\n".join(out)


def extract_faq(body_md: str) -> list[tuple[str, str]]:
    """Pull Q/A pairs from a 'Quick FAQ' heading if present, for JSON-LD."""
    m = re.search(r"^##\s+Quick FAQ\s*$", body_md, re.M)
    if not m:
        return []
    rest = body_md[m.end():]
    nxt = re.search(r"^##\s+", rest, re.M)
    if nxt:
        rest = rest[: nxt.start()]
    faqs = []
    parts = re.split(r"^###\s+", rest, flags=re.M)
    for part in parts[1:]:
        lines = part.strip().splitlines()
        if not lines:
            continue
        q = lines[0].strip()
        a = " ".join(ln.strip() for ln in lines[1:] if ln.strip())
        if q and a:
            faqs.append((q, a))
    return faqs


def first_paragraph(body_md: str) -> str:
    for block in re.split(r"\n\s*\n", body_md.strip()):
        block = block.strip()
        if block.startswith("#"):
            continue
        text = re.sub(r"[*_[\]#>`]", "", block)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 40:
            return text
    return ""


def load_pins(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON array in {path}")
    return data


def load_articles(content_dir: Path) -> dict[str, dict]:
    articles = {}
    for path in sorted(content_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        pin_id = meta.get("id") or path.stem
        meta["id"] = pin_id
        meta["body"] = body
        meta["_path"] = str(path)
        articles[pin_id] = meta
    return articles


def process_image(src: Path, dest_stem: Path) -> dict:
    """Write webp + jpeg copies. Returns relative filenames and dimensions."""
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    webp = dest_stem.with_suffix(".webp")
    jpeg = dest_stem.with_suffix(".jpg")
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        # Keep 2:3 lifestyle frames reasonably sized for the web.
        max_w = 1200
        if w > max_w:
            ratio = max_w / w
            im = im.resize((max_w, int(h * ratio)), Image.Resampling.LANCZOS)
            w, h = im.size
        im.save(webp, "WEBP", quality=80, method=6)
        im.save(jpeg, "JPEG", quality=86, optimize=True)
    return {"webp": webp.name, "jpg": jpeg.name, "width": w, "height": h}


def page_shell(cfg, title, description, canonical_path, body, og=None, jsonld=None, extra_head=""):
    site = html.escape(cfg["site_name"])
    full_title = f"{title} · {cfg['site_name']}" if title != cfg["site_name"] else cfg["site_name"]
    desc = html.escape(description or cfg.get("description") or "")
    canonical = abs_url(cfg, canonical_path)
    og = og or {}
    og_title = html.escape(og.get("title") or title)
    og_desc = html.escape(og.get("description") or description or "")
    og_image = og.get("image") or abs_url(cfg, cfg.get("og_image_fallback") or "/images/og-default.jpg")
    og_type = og.get("type") or "website"
    og_w = og.get("width") or 1000
    og_h = og.get("height") or 1500
    published = og.get("published_time") or ""
    css = bp(cfg, "/css/style.css")
    home = bp(cfg, "/")
    about = bp(cfg, "/about/")
    disclosure = bp(cfg, "/disclosure/")
    feed = bp(cfg, "/feed.xml")
    favicon = bp(cfg, "/favicon.svg")
    article_time = ""
    if published:
        article_time = f'<meta property="article:published_time" content="{html.escape(published)}">'
    jsonld_html = ""
    if jsonld:
        jsonld_html = (
            '<script type="application/ld+json">'
            + json.dumps(jsonld, ensure_ascii=False)
            + "</script>"
        )
    year = date.today().year
    disclosure_txt = html.escape(cfg["disclosure"])
    return f"""<!DOCTYPE html>
<html lang="{html.escape(cfg.get('language','en'))}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(full_title)}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{html.escape(canonical)}">
  <link rel="icon" href="{favicon}" type="image/svg+xml">
  <link rel="alternate" type="application/rss+xml" title="{site} RSS" href="{feed}">
  <meta property="og:type" content="{html.escape(og_type)}">
  <meta property="og:site_name" content="{site}">
  <meta name="p:domain_verify" content="089ed43513335d03e342307af543eb71"/>
  <meta property="og:title" content="{og_title}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:url" content="{html.escape(canonical)}">
  <meta property="og:image" content="{html.escape(og_image)}">
  <meta property="og:image:width" content="{og_w}">
  <meta property="og:image:height" content="{og_h}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{og_title}">
  <meta name="twitter:description" content="{og_desc}">
  <meta name="twitter:image" content="{html.escape(og_image)}">
  {article_time}
  <meta name="robots" content="index,follow">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{css}">
  {extra_head}
  {jsonld_html}
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-inner">
      <a class="wordmark" href="{home}">{html.escape(cfg['site_name'].rsplit(' ', 1)[0] if ' ' in cfg['site_name'] else cfg['site_name'])}{(' <span>' + html.escape(cfg['site_name'].rsplit(' ', 1)[1]) + '</span>') if ' ' in cfg['site_name'] else ''}</a>
      <nav class="nav" aria-label="Primary">
        <a href="{home}">Latest</a>
        <a href="{about}">About</a>
        <a href="{disclosure}">Privacy &amp; Disclosure</a>
      </nav>
    </div>
  </header>
  <main id="main">
    {body}
  </main>
  <footer class="site-footer">
    <div class="wrap">
      <div class="footer-grid">
        <div>
          <strong>{site}</strong>
          <p>{html.escape(cfg.get('tagline') or '')}</p>
        </div>
        <div>
          <a href="{home}">Home</a><br>
          <a href="{about}">About</a><br>
          <a href="{disclosure}">Privacy &amp; Disclosure</a>
        </div>
        <div>
          <a href="{feed}">RSS feed</a><br>
          <span class="tiny">Prices are not listed here. Check Amazon for current pricing and availability.</span>
        </div>
      </div>
      <p class="disclosure-foot">{disclosure_txt}</p>
      <p class="tiny">© {year} {site}. Lifestyle photos on this site are mood images, not photos of the products themselves.</p>
    </div>
  </footer>
</body>
</html>
"""


def card_html(cfg, art) -> str:
    href = bp(cfg, f"/articles/{art['slug']}/")
    board_href = bp(cfg, f"/boards/{art['board_slug']}/")
    img = bp(cfg, f"/images/{art['image_webp']}")
    title = html.escape(art["title"])
    excerpt = html.escape(art["excerpt"][:160].rsplit(" ", 1)[0] + "…" if len(art["excerpt"]) > 160 else art["excerpt"])
    alt = html.escape(art["image_alt"])
    return f"""
    <a class="card" href="{href}">
      <div class="card-img"><img src="{img}" alt="{alt}" width="{art['image_w']}" height="{art['image_h']}" loading="lazy"></div>
      <div class="card-body">
        <div class="card-board">{html.escape(art['board'])}</div>
        <h3>{title}</h3>
        <p>{excerpt}</p>
      </div>
    </a>"""


def cta_block(cfg, art, leading=True) -> str:
    aff = html.escape(art["affiliate_link"], quote=True)
    pin = html.escape(art["pin_url"], quote=True)
    board = html.escape(art["board_url"], quote=True)
    product = html.escape(art["product_name"])
    board_name = html.escape(art["board"])
    lead = f"<p>Ready to look at current colors, sizes, and pricing for the {product}?</p>" if leading else ""
    return f"""
    {lead}
    <div class="cta-row">
      <a class="btn btn-amazon" href="{aff}" rel="sponsored nofollow noopener" target="_blank">Check price on Amazon</a>
      <a class="btn btn-pin" href="{pin}" rel="noopener" target="_blank">Save it on Pinterest</a>
      <a class="btn btn-ghost" href="{board}" rel="noopener" target="_blank">See the {board_name} board</a>
    </div>
    """


def build_article_list(cfg, pins, articles, out_images: Path) -> list[dict]:
    built = []
    missing = []
    for pin in pins:
        pin_id = pin["id"]
        if pin_id not in articles:
            missing.append(pin_id)
            continue
        meta = articles[pin_id]
        title = meta.get("title") or pin.get("title") or pin.get("product_name")
        slug = meta.get("slug") or slugify(pin.get("product_name") or title)
        src_image = Path(pin["image_path"])
        if not src_image.is_file():
            print(f"WARNING: missing image for {pin_id}: {src_image}", file=sys.stderr)
            continue
        # Cache-bust by source mtime + id
        dest = process_image(src_image, out_images / pin_id)
        excerpt = meta.get("description") or first_paragraph(meta["body"]) or pin.get("description", "").split("\n")[0]
        image_alt = meta.get("image_alt") or (
            "Lifestyle photo for mood and styling inspiration — not a photo of the product itself"
        )
        item = {
            **pin,
            "title": title,
            "slug": slug,
            "body": meta["body"],
            "excerpt": excerpt,
            "image_alt": image_alt,
            "image_webp": dest["webp"],
            "image_jpg": dest["jpg"],
            "image_w": dest["width"],
            "image_h": dest["height"],
            "board_slug": board_slug(pin["board"]),
            "faqs": extract_faq(meta["body"]),
        }
        built.append(item)
    built.sort(key=lambda a: (a.get("date_posted") or "", a["id"]), reverse=True)
    return built, missing


def render_home(cfg, arts, boards):
    pills = []
    for name, items in boards:
        href = bp(cfg, f"/boards/{board_slug(name)}/")
        pills.append(f'<a class="pill" href="{href}">{html.escape(name)} <span class="count">{len(items)}</span></a>')
    cards = "\n".join(card_html(cfg, a) for a in arts)
    body = f"""
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Pinterest-inspired Amazon finds</p>
        <h1>{html.escape(cfg['site_name'])}</h1>
        <p class="lede">{html.escape(cfg.get('tagline') or '')} New pin articles are added as each batch goes live. Lifestyle photos set the mood — they are not pictures of the products themselves.</p>
        <div class="board-pills">{''.join(pills)}</div>
      </div>
    </section>
    <div class="wrap">
      <div class="section-head"><h2>Latest finds</h2><p class="tiny">{len(arts)} article{"s" if len(arts)!=1 else ""}</p></div>
      <div class="grid">{cards}</div>
    </div>
    """
    jsonld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": cfg["site_name"],
        "description": cfg.get("description"),
        "url": abs_url(cfg, "/"),
    }
    return page_shell(cfg, cfg["site_name"], cfg.get("description"), "/", body, jsonld=jsonld)


def render_board(cfg, name, items, url):
    cards = "\n".join(card_html(cfg, a) for a in items)
    desc = f"Amazon finds from the {name} Pinterest board, each with a short article and a link to shop."
    body = f"""
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Board</p>
        <h1>{html.escape(name)}</h1>
        <p class="lede">{html.escape(desc)} Browse the board on Pinterest, or open an article to read more and check the current price on Amazon.</p>
        <div class="cta-row">
          <a class="btn btn-pin" href="{html.escape(items[0]['board_url'])}" rel="noopener" target="_blank">Open the {html.escape(name)} board</a>
        </div>
      </div>
    </section>
    <div class="wrap">
      <div class="grid">{cards}</div>
    </div>
    """
    return page_shell(cfg, name, desc, f"/boards/{board_slug(name)}/", body, og={"type": "website"})


def render_article(cfg, art):
    body_html = md_to_html(art["body"])
    # Insert a mid-article CTA before the FAQ heading if present.
    faq_split = re.split(r"(<h2>Quick FAQ</h2>)", body_html, maxsplit=1)
    if len(faq_split) == 3:
        prose = faq_split[0] + cta_block(cfg, art) + faq_split[1] + faq_split[2]
    else:
        prose = body_html + cta_block(cfg, art)
    prose += cta_block(cfg, art, leading=True)
    img = bp(cfg, f"/images/{art['image_webp']}")
    og_img = abs_url(cfg, f"/images/{art['image_jpg']}")
    board_href = bp(cfg, f"/boards/{art['board_slug']}/")
    published = art.get("date_posted") or ""
    # Prefer ISO date for display
    display_date = published
    caption = html.escape(art["image_alt"])
    body = f"""
    <div class="wrap article-hero">
      <p class="crumbs"><a href="{bp(cfg,'/')}">Home</a> / <a href="{board_href}">{html.escape(art['board'])}</a></p>
    </div>
    <article class="wrap article-layout">
      <figure class="article-photo">
        <img src="{img}" alt="{caption}" width="{art['image_w']}" height="{art['image_h']}">
        <figcaption class="caption">{caption}</figcaption>
      </figure>
      <div class="article-body">
        <p class="kicker">{html.escape(art['board'])}</p>
        <h1>{html.escape(art['title'])}</h1>
        <p class="article-meta">{html.escape(art['product_name'])} · Posted {html.escape(display_date)}</p>
        <p class="disclosure">{html.escape(cfg['disclosure'])}</p>
        <div class="prose faq">{prose}</div>
      </div>
    </article>
    """
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": art["title"],
        "description": art["excerpt"],
        "datePublished": published,
        "mainEntityOfPage": abs_url(cfg, f"/articles/{art['slug']}/"),
        "image": [og_img],
        "author": {"@type": "Organization", "name": cfg["site_name"]},
        "publisher": {"@type": "Organization", "name": cfg["site_name"]},
        "about": {"@type": "Product", "name": art["product_name"], "sku": art.get("asin")},
    }
    if art["faqs"]:
        jsonld["mainEntity"] = {
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in art["faqs"]
            ],
        }
        # FAQPage should be a separate graph node; keep it simple as additional type via @graph
        jsonld = {
            "@context": "https://schema.org",
            "@graph": [
                {k: v for k, v in jsonld.items() if k != "mainEntity"},
                {
                    "@type": "FAQPage",
                    "mainEntity": [
                        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                        for q, a in art["faqs"]
                    ],
                },
            ],
        }
    return page_shell(
        cfg,
        art["title"],
        art["excerpt"][:300],
        f"/articles/{art['slug']}/",
        body,
        og={
            "type": "article",
            "title": art["title"],
            "description": art["excerpt"][:200],
            "image": og_img,
            "width": art["image_w"],
            "height": art["image_h"],
            "published_time": published,
        },
        jsonld=jsonld,
    )


def render_about(cfg, count, boards):
    board_list = ", ".join(html.escape(n) for n, _ in boards) or "new boards as they appear"
    body = f"""
    <div class="wrap page">
      <p class="kicker">About</p>
      <h1>Why {html.escape(cfg['site_name'])} exists</h1>
      <p>{html.escape(cfg['site_name'])} is a simple storefront for Amazon finds that first showed up as Pinterest pins. Each pin gets its own article: who the item is for, the features listed for that product, ideas for wearing or using it, and a clear path to check the current price on Amazon or save the pin.</p>
      <p>The collection is meant to grow. New articles are added as new pins are published, across boards such as {board_list}.</p>
      <h2>About the photos</h2>
      <p>The images on this site are lifestyle or mood photos. They are <strong>not</strong> photographs of the exact products in the articles. Use them for vibe and styling inspiration, and rely on the Amazon listing for official product photos, colors, and sizing.</p>
      <h2>About the links</h2>
      <p>{html.escape(cfg['disclosure'])} When you buy through an Amazon link on this site, we may earn a commission, at no extra cost to you. We do not show static prices because Amazon prices and availability change.</p>
      <p>There {('are ' + str(count) + ' articles') if count != 1 else 'is 1 article'} on the site right now. Start with the <a href="{bp(cfg,'/')}">latest finds</a>, or read the <a href="{bp(cfg,'/disclosure/')}">Privacy &amp; Disclosure</a> page for the full affiliate and privacy notes.</p>
    </div>
    """
    return page_shell(cfg, "About", f"About {cfg['site_name']}, a Pinterest-inspired Amazon finds storefront.", "/about/", body)


def render_disclosure(cfg):
    body = f"""
    <div class="wrap page">
      <p class="kicker">Legal</p>
      <h1>Privacy &amp; Disclosure</h1>
      <h2>Amazon Associates disclosure</h2>
      <p class="disclosure">{html.escape(cfg['disclosure'])}</p>
      <p>{html.escape(cfg['site_name'])} is a participant in the Amazon Services LLC Associates Program, an affiliate advertising program designed to provide a means for sites to earn advertising fees by advertising and linking to Amazon.com and related sites. Amazon and the Amazon logo are trademarks of Amazon.com, Inc. or its affiliates.</p>
      <p>Links to Amazon on this site use the Associates tag <code>{html.escape(cfg['associates_tag'])}</code> and are marked with <code>rel="sponsored nofollow noopener"</code>. If you click a link and later buy something, we may earn a commission, at no additional cost to you. We do not list prices on this site because they change. Always confirm price, shipping, colors, sizing, and return terms on Amazon before you buy.</p>
      <h2>Pinterest</h2>
      <p>Articles also link to the public Pinterest pin and board that inspired them. Those links go to Pinterest and are subject to Pinterest’s own terms and privacy policy. This site is not affiliated with Pinterest, Inc.</p>
      <h2>Photos</h2>
      <p>Lifestyle images used on article pages are mood and styling photos. They are not photographs of the products being discussed. Product appearance, color, and details should be confirmed on the Amazon listing.</p>
      <h2>Privacy</h2>
      <p>This is a static website. We do not run a member account system, and we do not ask you to submit a name, email address, or payment details on this site. We do not set first-party analytics cookies from this repository’s own code. If you follow a link to Amazon, Pinterest, or another third-party site, that site may collect data under its own privacy policy. If this site is later served through a host or CDN that logs basic request data (such as IP address and browser type), those logs are controlled by the host, not stored in this project.</p>
      <p>If a future version of the site adds a newsletter, comments, or other forms, this page will be updated to describe what is collected and why.</p>
      <h2>Accuracy</h2>
      <p>Product features in the articles are based on publicly listed product information at the time of writing. Listings can change. We do not invent specifications, ratings, reviews, or testimonials, and we do not guarantee that a product will meet your needs. Check the live Amazon page for the latest details.</p>
    </div>
    """
    return page_shell(
        cfg,
        "Privacy & Disclosure",
        f"Amazon Associates disclosure and privacy notes for {cfg['site_name']}.",
        "/disclosure/",
        body,
    )


def write_robots(cfg, dest: Path):
    sitemap = abs_url(cfg, "/sitemap.xml")
    dest.write_text(f"User-agent: *\nAllow: /\nSitemap: {sitemap}\n", encoding="utf-8")


def write_sitemap(cfg, arts, dest: Path):
    urls = [("/", "weekly", "1.0"), ("/about/", "monthly", "0.5"), ("/disclosure/", "monthly", "0.4")]
    seen_boards = set()
    for a in arts:
        if a["board_slug"] not in seen_boards:
            urls.append((f"/boards/{a['board_slug']}/", "weekly", "0.7"))
            seen_boards.add(a["board_slug"])
        urls.append((f"/articles/{a['slug']}/", "monthly", "0.8"))
    chunks = []
    today = date.today().isoformat()
    for path, freq, pri in urls:
        chunks.append(
            f"  <url><loc>{html.escape(abs_url(cfg, path))}</loc>"
            f"<changefreq>{freq}</changefreq><priority>{pri}</priority>"
            f"<lastmod>{today}</lastmod></url>"
        )
    dest.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(chunks)
        + "\n</urlset>\n",
        encoding="utf-8",
    )


def write_rss(cfg, arts, dest: Path):
    items = []
    for a in arts[:50]:
        link = abs_url(cfg, f"/articles/{a['slug']}/")
        pub = a.get("date_posted") or date.today().isoformat()
        # midnight UTC of the posted date
        try:
            dt = datetime.strptime(pub, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            rfc = dt.strftime("%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            rfc = pub
        items.append(
            f"""  <item>
    <title>{html.escape(a['title'])}</title>
    <link>{html.escape(link)}</link>
    <guid>{html.escape(link)}</guid>
    <pubDate>{rfc}</pubDate>
    <description>{html.escape(a['excerpt'])}</description>
  </item>"""
        )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{html.escape(cfg['site_name'])}</title>
  <link>{html.escape(abs_url(cfg, '/'))}</link>
  <description>{html.escape(cfg.get('description') or cfg.get('tagline') or '')}</description>
  <language>en-us</language>
{chr(10).join(items)}
</channel>
</rss>
"""
    dest.write_text(xml, encoding="utf-8")


def write_favicon(dest: Path, name: str):
    letter = html.escape((name or "J")[0].upper())
    dest.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#b44528"/>
  <text x="32" y="44" text-anchor="middle" font-size="36" font-family="Georgia, serif" fill="#fffcf7">{letter}</text>
</svg>
""",
        encoding="utf-8",
    )


def main() -> int:
    cfg = load_config()
    pins_path = Path(cfg["pins_json"])
    if not pins_path.is_file():
        print(f"ERROR: pins.json not found at {pins_path}", file=sys.stderr)
        return 1
    content_dir = ROOT / cfg.get("content_dir", "content")
    out = ROOT / cfg.get("output_dir", "docs")
    out_images = out / "images"
    out_css = out / "css"
    out.mkdir(parents=True, exist_ok=True)
    out_images.mkdir(parents=True, exist_ok=True)
    out_css.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "static" / "css" / "style.css", out_css / "style.css")
    write_favicon(out / "favicon.svg", cfg["site_name"])
    og_src = ROOT / "static" / "img" / "og-default.jpg"
    if og_src.is_file():
        shutil.copy2(og_src, out_images / "og-default.jpg")

    pins = load_pins(pins_path)
    articles = load_articles(content_dir)
    built, missing = build_article_list(cfg, pins, articles, out_images)

    if missing:
        print(f"NOTE: {len(missing)} pin(s) have no content file yet: {', '.join(missing)}")
        print("Write content/<id>.md for each, then rerun generate.py. See README.md.")

    boards_map = defaultdict(list)
    for a in built:
        boards_map[a["board"]].append(a)
    boards = sorted(boards_map.items(), key=lambda kv: kv[0].lower())

    # Home
    (out / "index.html").write_text(render_home(cfg, built, boards), encoding="utf-8")

    # About + disclosure
    about_dir = out / "about"
    about_dir.mkdir(exist_ok=True)
    (about_dir / "index.html").write_text(render_about(cfg, len(built), boards), encoding="utf-8")
    disc_dir = out / "disclosure"
    disc_dir.mkdir(exist_ok=True)
    (disc_dir / "index.html").write_text(render_disclosure(cfg), encoding="utf-8")

    # Boards
    for name, items in boards:
        bdir = out / "boards" / board_slug(name)
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "index.html").write_text(render_board(cfg, name, items, items[0]["board_url"]), encoding="utf-8")

    # Articles
    # Clean removed slugs? Keep it simple: write current ones; leftover old pages can remain.
    for art in built:
        adir = out / "articles" / art["slug"]
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "index.html").write_text(render_article(cfg, art), encoding="utf-8")

    write_robots(cfg, out / "robots.txt")
    write_sitemap(cfg, built, out / "sitemap.xml")
    write_rss(cfg, built, out / "feed.xml")

    # A tiny .nojekyll so GitHub Pages does not run Jekyll on docs/
    (out / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Built {len(built)} article(s), {len(boards)} board page(s) → {out}")
    if missing:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
