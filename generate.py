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
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from PIL import Image

PACIFIC = ZoneInfo("America/Los_Angeles")
OG_WIDE = (1200, 630)

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


def iso_datetime(day: str) -> str:
    """YYYY-MM-DD -> ISO 8601 datetime at local midnight in America/Los_Angeles."""
    try:
        dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        return dt.isoformat()
    except (ValueError, TypeError):
        return day or ""


def file_mtime_iso(path: str | Path | None) -> str:
    if not path:
        return ""
    pth = Path(path)
    if not pth.is_file():
        return ""
    return datetime.fromtimestamp(pth.stat().st_mtime, tz=PACIFIC).replace(microsecond=0).isoformat()


def later_iso(*values: str) -> str:
    parsed = []
    for v in values:
        if not v:
            continue
        try:
            parsed.append(datetime.fromisoformat(v))
        except ValueError:
            continue
    if not parsed:
        return values[-1] if values else ""
    return max(parsed).isoformat()


def pinterest_profile_url(cfg: dict, items: list[dict] | None = None) -> str | None:
    """Return the Pinterest profile URL from config or from a board_url. Never invent one."""
    raw = (cfg.get("pinterest_profile") or "").strip()
    if raw:
        return raw.rstrip("/") + "/"
    for item in items or []:
        url = (item.get("board_url") or "").strip()
        if not url:
            continue
        parsed = urlparse(url)
        if "pinterest.com" not in (parsed.netloc or "").lower():
            continue
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return f"{parsed.scheme or 'https'}://{parsed.netloc}/{parts[0]}/"
    return None


def org_id(cfg: dict) -> str:
    return abs_url(cfg, "/") + "#organization"


def site_id(cfg: dict) -> str:
    return abs_url(cfg, "/") + "#website"


def logo_url(cfg: dict) -> str:
    return abs_url(cfg, "/images/logo.png")


def organization_node(cfg: dict, same_as: list[str] | None = None) -> dict:
    node = {
        "@type": "Organization",
        "@id": org_id(cfg),
        "name": cfg["site_name"],
        "url": abs_url(cfg, "/"),
        "logo": {
            "@type": "ImageObject",
            "url": logo_url(cfg),
            "width": 512,
            "height": 512,
        },
    }
    if same_as:
        node["sameAs"] = same_as
    return node


def website_node(cfg: dict) -> dict:
    return {
        "@type": "WebSite",
        "@id": site_id(cfg),
        "name": cfg["site_name"],
        "description": cfg.get("description") or cfg.get("tagline") or "",
        "url": abs_url(cfg, "/"),
        "inLanguage": cfg.get("language") or "en",
        "publisher": {"@id": org_id(cfg)},
    }


def board_niche(items: list[dict]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        niche = (item.get("niche") or "").strip()
        if niche:
            counts[niche] += 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def board_copy(name: str, items: list[dict]) -> tuple[str, str, str]:
    """Unique title, meta description, and lede from real board data only."""
    n = len(items)
    niche = board_niche(items)
    article_word = "article" if n == 1 else "articles"
    title = f"{name} – Amazon finds"
    covering = f", covering {niche}" if niche else ""
    desc = (
        f"Amazon finds from the {name} Pinterest board{covering}. "
        f"{n} short {article_word}, each with a link to the pin and a path to check the current price on Amazon."
    )
    lede = (
        f"{desc} Browse the board on Pinterest, or open an article to read more. "
        "Lifestyle photos on these pages set the mood — they are not pictures of the products themselves."
    )
    return title, desc, lede


def crumbs_html(cfg: dict, trail: list[tuple[str, str | None]]) -> str:
    """Visible breadcrumb nav. The last item is the current page (no link) if path is None or is the current page."""
    parts = []
    last_i = len(trail) - 1
    for i, (label, path) in enumerate(trail):
        text = html.escape(label)
        is_last = i == last_i
        if is_last or not path:
            parts.append(f'<li><span aria-current="page">{text}</span></li>')
        else:
            parts.append(f'<li><a href="{html.escape(bp(cfg, path))}">{text}</a></li>')
    return (
        '<nav class="crumbs" aria-label="Breadcrumb"><ol>'
        + "".join(parts)
        + "</ol></nav>"
    )


def breadcrumb_list(cfg: dict, trail: list[tuple[str, str]]) -> dict:
    elements = []
    for i, (label, path) in enumerate(trail, start=1):
        elements.append({
            "@type": "ListItem",
            "position": i,
            "name": label,
            "item": abs_url(cfg, path),
        })
    return {
        "@type": "BreadcrumbList",
        "itemListElement": elements,
    }


def cover_crop(im: Image.Image, tw: int, th: int) -> Image.Image:
    w, h = im.size
    if w == 0 or h == 0:
        return im
    scale = max(tw / w, th / h)
    nw, nh = max(tw, int(round(w * scale))), max(th, int(round(h * scale)))
    resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return resized.crop((left, top, left + tw, top + th))


def write_og_crop(src: Path, dest: Path, size: tuple[int, int] = OG_WIDE) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tw, th = size
    with Image.open(src) as im:
        cropped = cover_crop(im.convert("RGB"), tw, th)
        cropped.save(dest, "JPEG", quality=86, optimize=True)
    return {"jpg": dest.name, "width": tw, "height": th}


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


def page_shell(cfg, title, description, canonical_path, body, og=None, jsonld=None, extra_head="", html_title=None):
    site = html.escape(cfg["site_name"])
    if html_title:
        full_title = html_title
    elif title != cfg["site_name"]:
        full_title = f"{title} · {cfg['site_name']}"
    else:
        full_title = cfg.get("home_title") or cfg["site_name"]
    desc = html.escape(description or cfg.get("description") or "")
    canonical = abs_url(cfg, canonical_path)
    og = og or {}
    og_title = html.escape(og.get("title") or title)
    og_desc = html.escape(og.get("description") or description or "")
    og_fallback = cfg.get("og_image_wide") or cfg.get("og_image_fallback") or "/images/og-default-wide.jpg"
    og_image = og.get("image") or abs_url(cfg, og_fallback)
    og_type = og.get("type") or "website"
    og_w = og.get("width") or 1200
    og_h = og.get("height") or 630
    published = og.get("published_time") or ""
    modified = og.get("modified_time") or ""
    section = og.get("section") or ""
    css = bp(cfg, "/css/style.css")
    home = bp(cfg, "/")
    about = bp(cfg, "/about/")
    disclosure = bp(cfg, "/disclosure/")
    feed = bp(cfg, "/feed.xml")
    favicon = bp(cfg, "/favicon.svg")
    favicon_png = bp(cfg, "/favicon-192.png")
    article_meta = []
    if published:
        article_meta.append(f'<meta property="article:published_time" content="{html.escape(published)}">')
    if modified:
        article_meta.append(f'<meta property="article:modified_time" content="{html.escape(modified)}">')
    if section:
        article_meta.append(f'<meta property="article:section" content="{html.escape(section)}">')
    article_time = "\n  ".join(article_meta)
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
  <link rel="icon" href="{favicon_png}" type="image/png" sizes="192x192">
  <link rel="apple-touch-icon" href="{favicon_png}">
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
        og = write_og_crop(src_image, out_images / f"{pin_id}-og.jpg")
        excerpt = meta.get("description") or first_paragraph(meta["body"]) or pin.get("description", "").split("\n")[0]
        generic_alt = "Lifestyle photo for mood and styling inspiration — not a photo of the product itself"
        product = pin.get("product_name") or title
        image_alt = (meta.get("image_alt") or "").strip()
        if not image_alt or image_alt == generic_alt:
            image_alt = (
                f"Lifestyle photo for mood and styling inspiration — not a photo of {product}"
            )
        published = pin.get("date_posted") or ""
        published_iso = iso_datetime(published) if published else ""
        modified_iso = later_iso(published_iso, file_mtime_iso(meta.get("_path")))
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
            "og_image": og["jpg"],
            "og_w": og["width"],
            "og_h": og["height"],
            "board_slug": board_slug(pin["board"]),
            "faqs": extract_faq(meta["body"]),
            "date_published_iso": published_iso,
            "date_modified_iso": modified_iso,
        }
        built.append(item)
    built.sort(key=lambda a: (a.get("date_posted") or "", a["id"]), reverse=True)
    return built, missing


def render_home(cfg, arts, boards, same_as):
    pills = []
    for name, items in boards:
        href = bp(cfg, f"/boards/{board_slug(name)}/")
        pills.append(f'<a class="pill" href="{href}">{html.escape(name)} <span class="count">{len(items)}</span></a>')
    cards = "\n".join(card_html(cfg, a) for a in arts)
    home_title = cfg.get("home_title") or f"{cfg['site_name']} – Amazon picks from Pinterest boards"
    desc = cfg.get("description") or ""
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
        "@graph": [
            organization_node(cfg, same_as),
            website_node(cfg),
        ],
    }
    return page_shell(
        cfg,
        cfg["site_name"],
        desc,
        "/",
        body,
        og={
            "type": "website",
            "title": home_title,
            "description": desc,
        },
        jsonld=jsonld,
        html_title=home_title,
    )


def render_board(cfg, name, items, url, same_as):
    cards = "\n".join(card_html(cfg, a) for a in items)
    title, desc, lede = board_copy(name, items)
    board_path = f"/boards/{board_slug(name)}/"
    crumbs = crumbs_html(cfg, [("Home", "/"), (name, None)])
    body = f"""
    <div class="wrap article-hero">{crumbs}</div>
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Board</p>
        <h1>{html.escape(name)}</h1>
        <p class="lede">{html.escape(lede)}</p>
        <div class="cta-row">
          <a class="btn btn-pin" href="{html.escape(items[0]['board_url'])}" rel="noopener" target="_blank">Open the {html.escape(name)} board</a>
        </div>
      </div>
    </section>
    <div class="wrap">
      <div class="grid">{cards}</div>
    </div>
    """
    item_list = {
        "@type": "ItemList",
        "numberOfItems": len(items),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "url": abs_url(cfg, f"/articles/{art['slug']}/"),
                "name": art["title"],
            }
            for i, art in enumerate(items, start=1)
        ],
    }
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            organization_node(cfg, same_as),
            {
                "@type": "CollectionPage",
                "name": title,
                "description": desc,
                "url": abs_url(cfg, board_path),
                "isPartOf": {"@id": site_id(cfg)},
                "breadcrumb": breadcrumb_list(cfg, [("Home", "/"), (name, board_path)]),
                "mainEntity": item_list,
            },
        ],
    }
    return page_shell(
        cfg,
        title,
        desc,
        board_path,
        body,
        og={"type": "website", "title": title, "description": desc},
        jsonld=jsonld,
    )


def render_article(cfg, art, related, same_as):
    body_html = md_to_html(art["body"])
    # Insert a mid-article CTA before the FAQ heading if present.
    faq_split = re.split(r"(<h2>Quick FAQ</h2>)", body_html, maxsplit=1)
    if len(faq_split) == 3:
        prose = faq_split[0] + cta_block(cfg, art) + faq_split[1] + faq_split[2]
    else:
        prose = body_html + cta_block(cfg, art)
    prose += cta_block(cfg, art, leading=True)
    img = bp(cfg, f"/images/{art['image_webp']}")
    og_img = abs_url(cfg, f"/images/{art['og_image']}")
    board_href = bp(cfg, f"/boards/{art['board_slug']}/")
    article_path = f"/articles/{art['slug']}/"
    published = art.get("date_posted") or ""
    published_iso = art.get("date_published_iso") or iso_datetime(published)
    modified_iso = art.get("date_modified_iso") or published_iso
    display_date = published
    caption = html.escape(art["image_alt"])
    crumbs = crumbs_html(cfg, [("Home", "/"), (art["board"], f"/boards/{art['board_slug']}/"), (art["title"], None)])
    related_html = ""
    if related:
        cards = "\n".join(card_html(cfg, a) for a in related)
        related_html = f"""
    <section class="wrap related" aria-labelledby="related-heading">
      <div class="section-head">
        <h2 id="related-heading">More from {html.escape(art['board'])}</h2>
        <p class="tiny"><a href="{board_href}">See the full board</a></p>
      </div>
      <div class="grid">{cards}</div>
    </section>
    """
    body = f"""
    <div class="wrap article-hero">{crumbs}</div>
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
    {related_html}
    """
    article_node = {
        "@type": "Article",
        "headline": art["title"],
        "description": art["excerpt"],
        "datePublished": published_iso,
        "dateModified": modified_iso,
        "mainEntityOfPage": abs_url(cfg, article_path),
        "image": [og_img],
        "author": {
            "@type": "Organization",
            "name": cfg["site_name"],
            "url": abs_url(cfg, "/about/"),
        },
        "publisher": {"@id": org_id(cfg)},
        "articleSection": art["board"],
        "about": {"@type": "Product", "name": art["product_name"], "sku": art.get("asin")},
    }
    graph = [
        organization_node(cfg, same_as),
        article_node,
        breadcrumb_list(cfg, [
            ("Home", "/"),
            (art["board"], f"/boards/{art['board_slug']}/"),
            (art["title"], article_path),
        ]),
    ]
    if art["faqs"]:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in art["faqs"]
            ],
        })
    jsonld = {"@context": "https://schema.org", "@graph": graph}
    preload = f'<link rel="preload" as="image" href="{html.escape(img)}" type="image/webp">'
    return page_shell(
        cfg,
        art["title"],
        art["excerpt"][:300],
        article_path,
        body,
        og={
            "type": "article",
            "title": art["title"],
            "description": art["excerpt"][:200],
            "image": og_img,
            "width": art["og_w"],
            "height": art["og_h"],
            "published_time": published_iso,
            "modified_time": modified_iso,
            "section": art["board"],
        },
        jsonld=jsonld,
        extra_head=preload,
    )


def render_about(cfg, count, boards, same_as):
    board_list = ", ".join(html.escape(n) for n, _ in boards) or "new boards as they appear"
    crumbs = crumbs_html(cfg, [("Home", "/"), ("About", None)])
    body = f"""
    <div class="wrap page">
      {crumbs}
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
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            organization_node(cfg, same_as),
            {
                "@type": "AboutPage",
                "name": f"About {cfg['site_name']}",
                "url": abs_url(cfg, "/about/"),
                "isPartOf": {"@id": site_id(cfg)},
                "breadcrumb": breadcrumb_list(cfg, [("Home", "/"), ("About", "/about/")]),
            },
        ],
    }
    return page_shell(
        cfg,
        "About",
        f"About {cfg['site_name']}, a Pinterest-inspired Amazon finds storefront.",
        "/about/",
        body,
        jsonld=jsonld,
    )


def render_disclosure(cfg, same_as):
    crumbs = crumbs_html(cfg, [("Home", "/"), ("Privacy & Disclosure", None)])
    body = f"""
    <div class="wrap page">
      {crumbs}
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
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            organization_node(cfg, same_as),
            {
                "@type": "WebPage",
                "name": "Privacy & Disclosure",
                "url": abs_url(cfg, "/disclosure/"),
                "isPartOf": {"@id": site_id(cfg)},
                "breadcrumb": breadcrumb_list(cfg, [("Home", "/"), ("Privacy & Disclosure", "/disclosure/")]),
            },
        ],
    }
    return page_shell(
        cfg,
        "Privacy & Disclosure",
        f"Amazon Associates disclosure and privacy notes for {cfg['site_name']}.",
        "/disclosure/",
        body,
        jsonld=jsonld,
    )


def write_robots(cfg, dest: Path):
    sitemap = abs_url(cfg, "/sitemap.xml")
    dest.write_text(f"User-agent: *\nAllow: /\nSitemap: {sitemap}\n", encoding="utf-8")


def lastmod_day(value: str) -> str:
    """Reduce an ISO datetime or YYYY-MM-DD value to a sitemap lastmod date."""
    if not value:
        return ""
    return value[:10]


def write_sitemap(cfg, arts, dest: Path):
    latest = ""
    board_latest = {}
    for a in arts:
        day = lastmod_day(a.get("date_modified_iso") or a.get("date_published_iso") or a.get("date_posted") or "")
        if day and day > latest:
            latest = day
        slug = a["board_slug"]
        if day and day > board_latest.get(slug, ""):
            board_latest[slug] = day
    urls = [
        ("/", "weekly", "1.0", latest),
        ("/about/", "monthly", "0.5", latest),
        ("/disclosure/", "monthly", "0.4", latest),
    ]
    seen_boards = set()
    for a in arts:
        if a["board_slug"] not in seen_boards:
            urls.append((f"/boards/{a['board_slug']}/", "weekly", "0.7", board_latest.get(a["board_slug"], latest)))
            seen_boards.add(a["board_slug"])
        art_day = lastmod_day(a.get("date_modified_iso") or a.get("date_published_iso") or a.get("date_posted") or latest)
        urls.append((f"/articles/{a['slug']}/", "monthly", "0.8", art_day))
    chunks = []
    for path, freq, pri, lastmod in urls:
        lastmod_xml = f"<lastmod>{html.escape(lastmod)}</lastmod>" if lastmod else ""
        chunks.append(
            f"  <url><loc>{html.escape(abs_url(cfg, path))}</loc>"
            f"<changefreq>{freq}</changefreq><priority>{pri}</priority>"
            f"{lastmod_xml}</url>"
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


def write_lettermark_png(dest: Path, name: str, size: int):
    """Raster of the same lettermark used for the SVG favicon."""
    from PIL import ImageDraw, ImageFont

    dest.parent.mkdir(parents=True, exist_ok=True)
    letter = (name or "J")[0].upper()
    im = Image.new("RGB", (size, size), "#b44528")
    draw = ImageDraw.Draw(im)
    # Prefer a serif-like face if the box has one; otherwise the default bitmap font.
    font = None
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
    ):
        if Path(path).is_file():
            font = ImageFont.truetype(path, size=int(size * 0.58))
            break
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), letter, font=font, fill="#fffcf7")
    im.save(dest, "PNG", optimize=True)


def write_indexnow_key(cfg: dict, dest_dir: Path):
    key = (cfg.get("indexnow_key") or "").strip()
    if not key:
        return
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        print(f"WARNING: ignoring invalid indexnow_key", flush=True)
        return
    (dest_dir / f"{key}.txt").write_text(key + "\n", encoding="utf-8")


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
    write_lettermark_png(out / "favicon-48.png", cfg["site_name"], 48)
    write_lettermark_png(out / "favicon-192.png", cfg["site_name"], 192)
    write_lettermark_png(out_images / "logo.png", cfg["site_name"], 512)
    og_src = ROOT / "static" / "img" / "og-default.jpg"
    if og_src.is_file():
        shutil.copy2(og_src, out_images / "og-default.jpg")
        write_og_crop(og_src, out_images / "og-default-wide.jpg")
    write_indexnow_key(cfg, out)

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

    profile = pinterest_profile_url(cfg, built or pins)
    same_as = [profile] if profile else []

    # Home
    (out / "index.html").write_text(render_home(cfg, built, boards, same_as), encoding="utf-8")

    # About + disclosure
    about_dir = out / "about"
    about_dir.mkdir(exist_ok=True)
    (about_dir / "index.html").write_text(render_about(cfg, len(built), boards, same_as), encoding="utf-8")
    disc_dir = out / "disclosure"
    disc_dir.mkdir(exist_ok=True)
    (disc_dir / "index.html").write_text(render_disclosure(cfg, same_as), encoding="utf-8")

    # Boards
    for name, items in boards:
        bdir = out / "boards" / board_slug(name)
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "index.html").write_text(render_board(cfg, name, items, items[0]["board_url"], same_as), encoding="utf-8")

    # Articles
    # Clean removed slugs? Keep it simple: write current ones; leftover old pages can remain.
    for art in built:
        related = [other for other in boards_map[art["board"]] if other["id"] != art["id"]][:4]
        adir = out / "articles" / art["slug"]
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "index.html").write_text(render_article(cfg, art, related, same_as), encoding="utf-8")

    write_robots(cfg, out / "robots.txt")
    write_sitemap(cfg, built, out / "sitemap.xml")
    write_rss(cfg, built, out / "feed.xml")

    # A tiny .nojekyll so GitHub Pages does not run Jekyll on docs/
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "CNAME").write_text("joehartmann.com\n", encoding="utf-8")


    print(f"Built {len(built)} article(s), {len(boards)} board page(s) → {out}")
    if missing:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
