# Joe Hartmann Finds

A static affiliate storefront for Pinterest pins and their Amazon finds.

**Site name:** Joe Hartmann Finds (change this in one place: `config.json` → `site_name`, plus `tagline` and `description` if you want).

The live site is a [GitHub Pages](https://pages.github.com/) user site:

- Site: https://joehartmann.com/
- Repo: https://github.com/joesunderwater/joesunderwater.github.io

Pages is served from the `docs/` folder on the `main` branch. `docs/.nojekyll` is committed so GitHub does not run Jekyll on the output.

## How it works

- Affiliate Dave appends new pins to `/workspace/affiliate/pins.json` (a JSON array). Existing entries are never removed.
- Each pin gets **one article file**, `content/<pin-id>.md`, written once and never regenerated.
- `generate.py` merges those articles with the latest pin metadata (affiliate link, Pinterest URLs, image path, board) and writes a complete static site into `docs/`.

## Folder layout

```
affiliate-site/
  config.json              # site name, tagline, base_url, base_path, disclosure, paths
  generate.py              # static site generator (Python 3, Pillow only)
  update.sh                # detect new pins, then rebuild
  README.md
  content/
    _template.md           # copy this for each new article (not published)
    <pin-id>.md            # one article per pin; never overwrite
  scripts/
    list_new_pins.py       # prints new pins and writes build/new-pins.json
  static/css/style.css     # source stylesheet (copied into docs/ on build)
  docs/                    # BUILD OUTPUT — ready for GitHub Pages (`/docs` folder)
    index.html             # home, latest articles
    about/  disclosure/
    boards/<board-slug>/   # one category page per Pinterest board
    articles/<slug>/       # one article page per pin
    images/                # compressed webp + jpeg copies of lifestyle photos
    css/  favicon.svg  favicon-192.png
    sitemap.xml  robots.txt  feed.xml
    <indexnow-key>.txt        # IndexNow key file (from config.json)
  screenshots/             # local QA screenshots, not part of the public nav
  build/new-pins.json      # briefing file for the next article-writing batch
```

Pin source data (not in this folder): `/workspace/affiliate/pins.json`, with images at the absolute `image_path` on each entry.

## Config you will change later

In `config.json`:

- `site_name`, `tagline`, `description` — branding
- `base_url` — live site origin, `https://joehartmann.com` (used for canonical, sitemap, RSS, and Open Graph URLs).
- `home_title` — the homepage `<title>` and Open Graph title.
- `pinterest_profile` — the public Pinterest profile URL used in Organization `sameAs` markup. If omitted, the generator derives it from a pin `board_url`.
- `indexnow_key` — public IndexNow key. The build writes `docs/<key>.txt`, and `publish.sh` pings IndexNow with changed page URLs after a successful push.
- `base_path` — leave `""`. This is a user site at the domain root. Only set a path like `"/repo"` if you ever move it to a project site.
- `pins_json` — path to Dave’s pin file
- `output_dir` — `docs` (GitHub Pages can serve the `/docs` folder on the default branch; `.nojekyll` is written automatically)

## Daily / incremental update

Pins arrive in batches (about 20/day at first, ramping toward 200), usually after ~10:30 AM Pacific. Diff by `id`.

### 1. Detect new pins

```bash
cd /workspace/affiliate-site
./update.sh --check
# or:
python3 scripts/list_new_pins.py
```

This compares `pins.json` to `content/*.md` and writes `build/new-pins.json`: a briefing that contains every new pin’s fields (`id`, `title`, `product_name`, `asin`, `affiliate_link`, `pin_url`, `board`, `board_url`, `image_path`, and so on) plus counts. Existing articles are never listed as “new.”

### 2. Write articles for the new pins (AI batch of 20–200)

Article writing is **not** invented by the generator. A future AI run should:

1. Open `build/new-pins.json` (or the `--check` list).
2. Work through the `pins` array in batches if needed (20, 50, or the full day).
3. For **each** new pin, research the product with the **ASIN** and `product_name` (web search / the Amazon listing). Use only features you can confirm. If research fails, write a shorter article that stays inside the pin description and clearly avoids invented specs — and flag the pin in the run notes.
4. Create `content/<id>.md` from `content/_template.md`. The filename must match the pin `id` exactly (example: `content/2026-11-10-01.md`).
5. **Do not overwrite** a content file that already exists. If a file is present, skip that pin.
6. Then rebuild (step 3).

#### Article rules (every piece)

- Length: about **500–800 words**.
- Structure: intro, who it’s for, key features, how to use/style it, a **Quick FAQ**.
- The FAQ heading must be exactly `## Quick FAQ` so the generator can place CTA buttons in front of it and build FAQ structured data.
- Promote the product using confirmed features only. **Do not invent** specifications, prices, ratings, review counts, or testimonials. **Do not print a static price.**
- Lifestyle images are **not product photos**. Never caption or describe the site image as a picture of the item. Use an `image_alt` like the template’s default.
- Do not paste raw affiliate HTML. The generator injects:
  - a **Check price on Amazon** button that uses the exact `affiliate_link` from `pins.json`, with `rel="sponsored nofollow noopener"` and `target="_blank"`
  - a **Save it on Pinterest** link to `pin_url`
  - a link to `board_url`
- Keep Amazon disclosure out of the markdown body if you want; the page template already prints “As an Amazon Associate I earn from qualifying purchases.” on every article and in the footer.
- Front matter keys: `id` (required), `slug` (lowercase kebab-case; unique), `title`, `description` (meta/OG), `image_alt`.

Front-matter links are optional. At build time, `affiliate_link`, `pin_url`, `board`, `board_url`, `asin`, `product_name`, `date_posted`, and the image come from `pins.json` so those stay accurate even if a later pin file update corrects a URL. The prose in `content/<id>.md` is not rewritten.

### 3. Rebuild the site

```bash
cd /workspace/affiliate-site
./update.sh              # lists new pins, then builds
# or, if articles are already written:
./update.sh --build-only
# or:
python3 generate.py
```

Output goes to `docs/`. Preview locally (from `docs/`, so paths resolve):

```bash
python3 -m http.server --directory docs 8765
# open http://127.0.0.1:8765/
```

### 4. Publish to GitHub Pages

`./publish.sh` runs `git add -A && git commit`, then `git pull --rebase origin main`, then `git push`, **only if something changed**. It does not rebuild; run `./update.sh` first. The rebase avoids overwriting a concurrent daily publish. After a successful push it notifies IndexNow of changed page URLs; a failed ping prints a warning and does not fail the script. You can pass a commit message:

```bash
./publish.sh "Add 20 pin articles for 2026-11-11 and rebuild site"
```

If the working tree is clean, it prints `Nothing to publish` and exits 0 without an empty commit.

### Exact daily-run commands

Pins usually land in `/workspace/affiliate/pins.json` after about 10:30 AM Pacific. From this folder:

```bash
cd /workspace/affiliate-site
./update.sh --check
```

If new pins are listed, research each ASIN, write `content/<id>.md` from `content/_template.md` (do not overwrite existing files), then:

```bash
./update.sh --build-only
./publish.sh "Add <N> pin articles for YYYY-MM-DD and rebuild site"
```

If there were no new pins but you still need to rebuild and push (for example a config or CSS change):

```bash
./update.sh --build-only
./publish.sh
```

`./update.sh --publish` is a shortcut for “briefing + rebuild + publish.sh,” but only use it after today’s articles are already written. If new pins still lack content files, write those first, then `--build-only` and `./publish.sh`.

## Local quality checks

After a build, quickly confirm:

- Every article Amazon button URL still contains `tag=averagejoef04-20` (this is also required in `pins.json`).
- Pinterest pin and board links open the expected URLs.
- Lifestyle images load, and the caption does not call them product photos.
- The Associates disclosure appears on article pages and in the footer.
- New board names automatically get a `/boards/<slug>/` page.
- Article pages include visible breadcrumbs, BreadcrumbList JSON-LD, and a “More from this board” section.
- `docs/CNAME` is `joehartmann.com` and every page still has the `p:domain_verify` meta tag.
- `docs/<indexnow_key>.txt` is written when `indexnow_key` is set in `config.json`.

## Requirements

- Python 3.10+
- [Pillow](https://pypi.org/project/pillow/) (already used to write `.webp` and `.jpg` images)

No other generator dependencies. The site is plain HTML, CSS, and images.

## License / affiliate note

This is a private storefront project. Amazon and Pinterest names are trademarks of their owners. The site participates in the Amazon Associates program; see the Privacy & Disclosure page in the built site.
