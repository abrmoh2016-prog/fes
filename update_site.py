import hashlib
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# Ziel-URL hier eintragen (oder per Umgebungsvariable TARGET_URL übergeben)
TARGET_URL = os.getenv("TARGET_URL", "[DEINE_ZIEL_URL_HIER_EINFÜGEN]").strip()

BASE_TITLE = "وزارة الأوقاف والشؤون الإسلامية — مواقيت الصلاة وخطبة الجمعة"
HTML_FILENAME = f"{BASE_TITLE}.html"
ASSETS_DIRNAME = f"{BASE_TITLE}_files"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

CSS_URL_PATTERN = re.compile(r"""url\(\s*(['"]?)(?!data:|#)([^'")]+)\1\s*\)""", re.IGNORECASE)


def create_session() -> requests.Session:
    """Erstellt eine HTTP-Session mit realistischem User-Agent und UTF-8-Präferenz."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ar,fr;q=0.8,en-US;q=0.7,en;q=0.5",
            "Connection": "keep-alive",
        }
    )
    return session


def sanitize_filename(name: str, fallback_ext: str = "") -> str:
    """Bereinigt Dateinamen für das Dateisystem und bewahrt Unicode-/Arabisch-Zeichen."""
    name = unquote(name).strip()
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name)
    name = name.strip(" .")
    if not name:
        name = "asset"
    if fallback_ext and not Path(name).suffix:
        name = f"{name}{fallback_ext}"
    # Sehr lange Dateinamen kürzen, um Pfadprobleme zu vermeiden
    if len(name) > 120:
        stem = Path(name).stem[:100]
        suffix = Path(name).suffix[:16]
        name = f"{stem}{suffix}"
    return name


def build_local_asset_path(asset_url: str, assets_dir: Path, used_names: dict[str, str], default_ext: str = "") -> Path:
    """Erzeugt einen eindeutigen, lesbaren lokalen Dateipfad im Asset-Ordner."""
    if asset_url in used_names:
        return Path(used_names[asset_url])

    parsed = urlparse(asset_url)
    raw_name = Path(parsed.path).name
    ext = Path(raw_name).suffix.lower() if Path(raw_name).suffix else default_ext

    # Hash aus der vollständigen URL (inkl. Query-Parametern) verhindert Kollisionen
    url_hash = hashlib.sha1(asset_url.encode("utf-8")).hexdigest()[:8]
    stem = sanitize_filename(Path(raw_name).stem if raw_name else "resource")
    final_name = sanitize_filename(f"{stem}_{url_hash}{ext}")

    full_path = assets_dir / final_name
    counter = 1
    while full_path.exists() and full_path.name not in used_names.values():
        final_name = sanitize_filename(f"{stem}_{url_hash}_{counter}{ext}")
        full_path = assets_dir / final_name
        counter += 1

    used_names[asset_url] = final_name
    return full_path


def download_binary(session: requests.Session, url: str, referer: str | None = None, timeout: int = 25) -> tuple[bytes, str] | None:
    """Lädt eine Ressource fehlertolerant herunter und gibt (Inhalt, Content-Type) zurück."""
    headers = {"Referer": referer} if referer else {}
    try:
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "").lower()
        return resp.content, content_type
    except requests.RequestException as exc:
        print(f"[WARN] Konnte Ressource nicht laden ({url}): {exc}")
        return None


def rewrite_css_urls(
    css_text: str,
    css_url: str,
    session: requests.Session,
    assets_dir: Path,
    used_names: dict[str, str],
) -> str:
    """Lädt in CSS enthaltene url(...)-Assets herunter und schreibt sie auf relative Pfade um."""

    def replace_match(match: re.Match) -> str:
        raw_ref = match.group(2).strip()
        if not raw_ref or raw_ref.startswith(("data:", "blob:", "#")):
            return match.group(0)

        abs_asset_url = urljoin(css_url, raw_ref)
        downloaded = download_binary(session, abs_asset_url, referer=css_url)
        if not downloaded:
            return match.group(0)

        content, content_type = downloaded
        default_ext = ""
        if "font/woff2" in content_type or "woff2" in abs_asset_url.lower():
            default_ext = ".woff2"
        elif "font/woff" in content_type or "woff" in abs_asset_url.lower():
            default_ext = ".woff"
        elif "image/svg" in content_type or "svg" in abs_asset_url.lower():
            default_ext = ".svg"
        elif "image/png" in content_type or "png" in abs_asset_url.lower():
            default_ext = ".png"
        elif "image/jpeg" in content_type or "jpg" in abs_asset_url.lower():
            default_ext = ".jpg"

        local_file = build_local_asset_path(abs_asset_url, assets_dir, used_names, default_ext=default_ext)
        try:
            local_file.write_bytes(content)
        except OSError as exc:
            print(f"[WARN] Konnte CSS-Asset nicht speichern ({local_file}): {exc}")
            return match.group(0)

        # CSS-Dateien liegen direkt in assets_dir, daher ist der Dateiname selbst der relative Pfad
        return f'url("{local_file.name}")'

    return CSS_URL_PATTERN.sub(replace_match, css_text)


def process_asset(
    raw_url: str,
    page_url: str,
    session: requests.Session,
    assets_dir: Path,
    assets_dirname: str,
    used_names: dict[str, str],
    default_ext: str = "",
    is_stylesheet: bool = False,
) -> str | None:
    """Lädt ein Asset herunter, verarbeitet ggf. CSS-Inhalte und gibt den relativen HTML-Pfad zurück."""
    if not raw_url or raw_url.strip().startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
        return None

    abs_url = urljoin(page_url, raw_url.strip())
    downloaded = download_binary(session, abs_url, referer=page_url)
    if not downloaded:
        return None

    content, content_type = downloaded
    ext = default_ext
    if not ext:
        if "text/css" in content_type or abs_url.lower().endswith(".css"):
            ext = ".css"
        elif "application/javascript" in content_type or "text/javascript" in content_type or abs_url.lower().endswith(".js"):
            ext = ".js"
        elif "image/png" in content_type:
            ext = ".png"
        elif "image/jpeg" in content_type or "image/jpg" in content_type:
            ext = ".jpg"
        elif "image/webp" in content_type:
            ext = ".webp"
        elif "image/svg+xml" in content_type:
            ext = ".svg"
        elif "image/gif" in content_type:
            ext = ".gif"

    local_path = build_local_asset_path(abs_url, assets_dir, used_names, default_ext=ext)

    try:
        if is_stylesheet or local_path.suffix.lower() == ".css":
            css_text = content.decode("utf-8", errors="replace")
            rewritten_css = rewrite_css_urls(css_text, abs_url, session, assets_dir, used_names)
            local_path.write_text(rewritten_css, encoding="utf-8")
        else:
            local_path.write_bytes(content)
    except OSError as exc:
        print(f"[WARN] Fehler beim Schreiben von {local_path}: {exc}")
        return None

    return f"{assets_dirname}/{local_path.name}"


def rewrite_srcset(
    srcset_value: str,
    page_url: str,
    session: requests.Session,
    assets_dir: Path,
    assets_dirname: str,
    used_names: dict[str, str],
) -> str:
    """Aktualisiert alle URLs innerhalb eines srcset-Attributs auf lokale relative Pfade."""
    parts = [p.strip() for p in srcset_value.split(",") if p.strip()]
    new_parts: list[str] = []

    for part in parts:
        tokens = part.split()
        if not tokens:
            continue
        candidate_url = tokens[0]
        descriptor = " ".join(tokens[1:])
        local_rel = process_asset(
            candidate_url,
            page_url,
            session,
            assets_dir,
            assets_dirname,
            used_names,
        )
        final_url = local_rel if local_rel else candidate_url
        new_parts.append(f"{final_url} {descriptor}".strip())

    return ", ".join(new_parts)


def mirror_website(target_url: str, html_filename: str, assets_dirname: str) -> None:
    if not target_url or target_url == "[DEINE_ZIEL_URL_HIER_EINFÜGEN]":
        raise ValueError("Bitte eine gültige Ziel-URL in TARGET_URL oder per Umgebungsvariable TARGET_URL angeben.")

    html_path = Path(html_filename)
    assets_dir = Path(assets_dirname)

    # 1. Alten Asset-Ordner vor jedem neuen Speichervorgang löschen
    if assets_dir.exists():
        print(f"[INFO] Lösche alten Asset-Ordner: {assets_dir}")
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    session = create_session()

    # 2. Hauptseite herunterladen
    print(f"[INFO] Lade Ziel-URL: {target_url}")
    response = session.get(target_url, timeout=30)
    response.raise_for_status()

    # Saubere UTF-8-Erkennung sicherstellen
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    html_text = response.text

    soup = BeautifulSoup(html_text, "html.parser")
    used_names: dict[str, str] = {}

    # 3. <link> Elemente (Stylesheets, Icons, Preloads)
    for link_tag in soup.find_all("link", href=True):
        href = link_tag.get("href", "").strip()
        rel_vals = [r.lower() for r in (link_tag.get("rel") or [])]
        is_css = "stylesheet" in rel_vals or href.lower().endswith(".css")
        as_attr = (link_tag.get("as") or "").lower()

        if is_css or any(r in rel_vals for r in ("icon", "shortcut icon", "apple-touch-icon")) or as_attr in ("style", "image", "font"):
            local_rel = process_asset(
                href,
                target_url,
                session,
                assets_dir,
                assets_dirname,
                used_names,
                default_ext=".css" if is_css else "",
                is_stylesheet=is_css,
            )
            if local_rel:
                link_tag["href"] = local_rel

    # 4. <script> Elemente mit src
    for script_tag in soup.find_all("script", src=True):
        src = script_tag.get("src", "").strip()
        local_rel = process_asset(
            src,
            target_url,
            session,
            assets_dir,
            assets_dirname,
            used_names,
            default_ext=".js",
        )
        if local_rel:
            script_tag["src"] = local_rel

    # 5. Bilder, Videos, Audio, Quellen und Poster (src & srcset)
    media_tags = soup.find_all(["img", "source", "video", "audio", "iframe"])
    for tag in media_tags:
        if tag.has_attr("src"):
            local_rel = process_asset(
                tag["src"],
                target_url,
                session,
                assets_dir,
                assets_dirname,
                used_names,
            )
            if local_rel:
                tag["src"] = local_rel

        if tag.has_attr("poster"):
            local_poster = process_asset(
                tag["poster"],
                target_url,
                session,
                assets_dir,
                assets_dirname,
                used_names,
            )
            if local_poster:
                tag["poster"] = local_poster

        if tag.has_attr("srcset") and tag["srcset"]:
            tag["srcset"] = rewrite_srcset(
                tag["srcset"],
                target_url,
                session,
                assets_dir,
                assets_dirname,
                used_names,
            )

    # 6. Inline-<style>-Blöcke mit url(...)
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_tag.string = rewrite_css_urls(
                style_tag.string,
                target_url,
                session,
                assets_dir,
                used_names,
            )

    # 7. Inline-style=""-Attribute mit url(...)
    for styled_tag in soup.find_all(style=True):
        styled_tag["style"] = rewrite_css_urls(
            styled_tag["style"],
            target_url,
            session,
            assets_dir,
            used_names,
        )

    # 8. Meta-Charset auf UTF-8 setzen/sicherstellen und HTML speichern
    meta_charset = soup.find("meta", attrs={"charset": True})
    if meta_charset:
        meta_charset["charset"] = "utf-8"

    output_html = soup.prettify() if False else str(soup)
    html_path.write_text(output_html, encoding="utf-8")
    print(f"[OK] Gespeichert: {html_path} ({len(used_names)} Assets in {assets_dirname})")


if __name__ == "__main__":
    mirror_website(TARGET_URL, HTML_FILENAME, ASSETS_DIRNAME)
