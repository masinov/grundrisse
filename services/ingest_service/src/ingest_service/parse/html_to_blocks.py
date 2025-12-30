from __future__ import annotations

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup, Tag


@dataclass(frozen=True)
class ParsedBlock:
    title: str | None
    block_type: str
    block_subtype: str | None
    order_index: int
    path: str | None
    paragraphs: list[str]
    author_override_name: str | None


def parse_html_to_blocks(html: str) -> list[ParsedBlock]:
    """
    Day-1 contract:
    - Strip site chrome/navigation.
    - Preserve headings and paragraph boundaries.
    - Detect preface/afterword/editorial apparatus as block_subtype.
    - Optionally detect authorship overrides (e.g., "Preface by Engels").
    """
    soup = BeautifulSoup(html, "lxml")

    container = _pick_main_container(soup)
    _strip_noise(container)

    blocks: list[ParsedBlock] = []
    current_title: str | None = None
    current_level: int = 1
    current_paras: list[str] = []
    current_author_override: str | None = None

    def flush() -> None:
        nonlocal current_title, current_level, current_paras, current_author_override
        if not current_paras and current_title is None:
            return
        order_index = len(blocks)
        block_type = _block_type_for_level(current_level)
        block_subtype = _infer_block_subtype(current_title)
        author_override = current_author_override or _infer_author_override(current_title)
        blocks.append(
            ParsedBlock(
                title=current_title,
                block_type=block_type,
                block_subtype=block_subtype,
                order_index=order_index,
                path=str(order_index + 1),
                paragraphs=current_paras,
                author_override_name=author_override,
            )
        )
        current_title = None
        current_level = 1
        current_paras = []
        current_author_override = None

    for node in container.descendants:
        if not isinstance(node, Tag):
            continue

        if node.name in {"h1", "h2", "h3", "h4"}:
            title_text = _clean_text(node.get_text(" ", strip=True))
            if title_text:
                flush()
                current_title = title_text
                current_level = int(node.name[1])
                inferred = _infer_author_override(title_text)
                if inferred:
                    current_author_override = inferred
            continue

        if node.name == "p":
            text = _clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            if _is_noise_paragraph(text):
                continue
            current_paras.append(text)

    flush()

    if not blocks:
        text = _clean_text(container.get_text("\n", strip=True))
        paras = [p.strip() for p in text.split("\n") if p.strip()]
        blocks = [
            ParsedBlock(
                title=None,
                block_type="chapter",
                block_subtype=None,
                order_index=0,
                path="1",
                paragraphs=paras,
                author_override_name=None,
            )
        ]

    return blocks


def _pick_main_container(soup: BeautifulSoup) -> Tag:
    for selector in [
        ("div", {"id": "content"}),
        ("div", {"class": "article"}),
        ("div", {"id": "article"}),
        ("div", {"id": "main"}),
        ("body", {}),
    ]:
        tag = soup.find(*selector)
        if isinstance(tag, Tag):
            return tag
    body = soup.body
    if isinstance(body, Tag):
        return body
    raise RuntimeError("Could not find HTML container")


def _strip_noise(container: Tag) -> None:
    for tag_name in ["script", "style", "nav", "header", "footer", "form"]:
        for t in list(container.find_all(tag_name)):
            t.decompose()
    for t in list(container.find_all("div", class_=re.compile(r"(nav|menu|footer|header)", re.I))):
        t.decompose()


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _block_type_for_level(level: int) -> str:
    if level <= 1:
        return "chapter"
    if level == 2:
        return "section"
    if level == 3:
        return "subsection"
    return "other"


def _infer_block_subtype(title: str | None) -> str | None:
    if not title:
        return None
    t = title.lower()
    if "preface" in t:
        return "preface"
    if "afterword" in t or "postface" in t:
        return "afterword"
    if "footnote" in t or "notes" in t:
        return "footnote"
    if "appendix" in t:
        return "appendix"
    return None


_BY_RE = re.compile(r"\bby\s+([A-Z][A-Za-z .'-]{2,80})\b")


def _infer_author_override(title: str | None) -> str | None:
    if not title:
        return None
    m = _BY_RE.search(title)
    if not m:
        return None
    candidate = m.group(1).strip()
    if len(candidate) < 3:
        return None
    return candidate


def _is_noise_paragraph(text: str) -> bool:
    t = text.lower()
    return (
        t.startswith("back to ")
        or t.startswith("back ")
        or "mia :" in t
        or "marxists internet archive" in t
        or t == "index"
    )
