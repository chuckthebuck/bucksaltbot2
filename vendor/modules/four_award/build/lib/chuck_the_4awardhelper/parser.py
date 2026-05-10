from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .config import FOUR_PAGE
from .models import FourAwardNomination
from .util import clean_wiki_value, normalize_title, split_users
from .wiki import get_wiki


def _section_body(text: str, heading: str) -> str:
    pattern = re.compile(rf"^(?P<marks>=+)\s*{re.escape(heading)}\s*(?P=marks)\s*$", re.M | re.I)
    match = pattern.search(text)
    if not match:
        return ""
    level = len(match.group("marks"))
    rest = text[match.end() :]
    next_heading = re.search(rf"^={{1,{level}}}[^=].*={{1,{level}}}\s*$", rest, re.M)
    return rest[: next_heading.start()] if next_heading else rest


def _iter_template_spans(text: str, template_name: str) -> List[Tuple[str, int]]:
    starts = [
        m.start()
        for m in re.finditer(r"\{\{\s*(?:subst:\s*)?" + re.escape(template_name), text, re.I)
    ]
    spans: List[Tuple[str, int]] = []
    for start in starts:
        depth = 0
        i = start
        while i < len(text) - 1:
            pair = text[i : i + 2]
            if pair == "{{":
                depth += 1
                i += 2
                continue
            if pair == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    spans.append((text[start:i], start))
                    break
                continue
            i += 1
    return spans


def _split_template_params(template_text: str) -> Dict[str, str]:
    body = template_text.strip()[2:-2]
    pieces: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(body):
        pair = body[i : i + 2]
        if pair in {"{{", "[["}:
            depth += 1
            current.append(pair)
            i += 2
            continue
        if pair in {"}}", "]]"} and depth:
            depth -= 1
            current.append(pair)
            i += 2
            continue
        if body[i] == "|" and depth == 0:
            pieces.append("".join(current))
            current = []
            i += 1
            continue
        current.append(body[i])
        i += 1
    pieces.append("".join(current))

    params: Dict[str, str] = {}
    for index, piece in enumerate(pieces[1:], start=1):
        if "=" in piece:
            key, value = piece.split("=", 1)
            params[key.strip().casefold()] = value.strip()
        else:
            params[str(index)] = piece.strip()
    return params


def _heading_before(text: str, offset: int) -> tuple[str, int]:
    headings = list(re.finditer(r"^={3,}\s*(.*?)\s*={3,}\s*$", text[:offset], re.M))
    if not headings:
        return "", 0
    return clean_wiki_value(headings[-1].group(1)), len(headings)


def _heading_blocks(text: str) -> list[tuple[str, int, str]]:
    headings = list(re.finditer(r"^={3,}\s*(.*?)\s*={3,}\s*$", text, re.M))
    blocks: list[tuple[str, int, str]] = []
    for index, heading in enumerate(headings):
        start = heading.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        blocks.append((clean_wiki_value(heading.group(1)), index + 1, text[start:end].strip()))
    return blocks


def _nomination_block(text: str, raw_template: str, offset: int) -> str:
    heading = list(re.finditer(r"^={3,}\s*.*?\s*={3,}\s*$", text[:offset], re.M))
    if not heading:
        return raw_template
    start = heading[-1].start()
    next_heading = re.search(r"^={3,}\s*.*?\s*={3,}\s*$", text[offset + len(raw_template) :], re.M)
    if not next_heading:
        return text[start:].strip()
    end = offset + len(raw_template) + next_heading.start()
    return text[start:end].strip()


def _first_link_after_label(block: str, label: str) -> str:
    match = re.search(rf"'''{re.escape(label)}'''\s*:\s*(.*)", block, re.I)
    if not match:
        return ""
    line = match.group(1)
    links = re.findall(r"\[\[([^|\]#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]", line)
    return normalize_title(links[-1]) if links else ""


def _link_after_label(block: str, label: str, fallback_index: int = -1) -> str:
    match = re.search(rf"'''{re.escape(label)}'''\s*:\s*(.*)", block, re.I)
    if not match:
        return ""
    line = match.group(1)
    links = re.findall(r"\[\[([^|\]#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]", line)
    if not links:
        return ""
    if len(links) > abs(fallback_index):
        return normalize_title(links[fallback_index])
    return normalize_title(links[-1])


def _first_date_after_label(block: str, label: str) -> str:
    match = re.search(rf"'''{re.escape(label)}'''\s*:\s*(.*)", block, re.I)
    if not match:
        return ""
    line = match.group(1)
    date_match = re.search(r"\b(\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{1,2}-\d{1,2})\b", line)
    return date_match.group(1) if date_match else ""


def _manual_nomination_from_block(section_title: str, section_index: int, block: str) -> FourAwardNomination | None:
    article_match = re.search(r"Article:\s*'''?\s*\[\[([^|\]#]+)", block, re.I)
    if not article_match:
        return None
    users = split_users(section_title)
    if not users:
        sig_users = re.findall(r"\[\[\s*User:([^|\]/#]+)", block, re.I)
        users = split_users(", ".join(sig_users))
    article = normalize_title(clean_wiki_value(article_match.group(1)))
    return FourAwardNomination(
        section_title=section_title or article,
        section_index=section_index,
        raw_text=block,
        users=users,
        article=article,
        dyknom=_first_link_after_label(block, "DYK"),
        dyk=_first_date_after_label(block, "DYK"),
        ga=_first_link_after_label(block, "GA"),
        fac=_link_after_label(block, "FA", 0),
    )


def parse_nominations(page_text: str | None = None) -> List[FourAwardNomination]:
    page_text = page_text if page_text is not None else get_wiki().get_text(FOUR_PAGE)
    nominations_text = _section_body(page_text, "Current nominations")
    if not nominations_text:
        return []

    nominations: List[FourAwardNomination] = []
    template_blocks: set[str] = set()
    for raw_template, offset in _iter_template_spans(nominations_text, "Four Award Nomination"):
        params = _split_template_params(raw_template)
        article = normalize_title(clean_wiki_value(params.get("article") or params.get("1")))
        users = split_users(params.get("user"))
        section_title, section_index = _heading_before(nominations_text, offset)
        raw_text = _nomination_block(nominations_text, raw_template, offset)
        template_blocks.add(raw_text)
        nominations.append(
            FourAwardNomination(
                section_title=section_title or article,
                section_index=section_index,
                raw_text=raw_text,
                users=users,
                article=article,
                dyknom=clean_wiki_value(params.get("dyknom")),
                dyk=clean_wiki_value(params.get("dyk")),
                ga=clean_wiki_value(params.get("ga")),
                fac=clean_wiki_value(params.get("fac")),
                comments=clean_wiki_value(params.get("comments")),
            )
        )
    for section_title, section_index, block in _heading_blocks(nominations_text):
        if block in template_blocks or "Article:" not in block:
            continue
        nomination = _manual_nomination_from_block(section_title, section_index, block)
        if nomination:
            nominations.append(nomination)
    nominations.sort(key=lambda nomination: nomination.section_index)
    return nominations
