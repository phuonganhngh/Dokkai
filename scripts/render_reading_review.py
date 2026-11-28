"""Compile annotated reading answers into Dokkai's static exam HTML."""

import argparse
from collections import defaultdict
from html import escape
import json
from pathlib import Path
import re

from lxml import html


TONES = {"meaning", "grammar", "tip"}
SOLUTION = re.compile(r'<details class="solution" id="solution-(\d+)">.*?</details>', re.S)
REVIEW_STYLE = """
<style id="reading-review-style">
.solution .review-evidence-caption { padding-block: 3px 6px; }
.solution .review-evidence-caption > span { display: inline; }
.review-evidence-caption > span + span::before { content: " "; }
.review-reference { margin-inline-start: .45em; color: #126c60; }
.solution .review-strip .scan-frame-cover { opacity: 1; mix-blend-mode: normal; fill: #fff; }
.review-quote mark[data-tone] { color: inherit; }
.review-quote mark[data-tone="meaning"] { background: #dfedd4; }
.review-quote mark[data-tone="grammar"] { background: #d0edf8; }
.review-quote mark[data-tone="tip"] { background: #fff5b7; }
</style>
"""


def intersect(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def supplementary_refs(references, locations):
    """Link to one additional citation per distant evidence group."""
    primary = locations[references[0]]
    seen = set()
    for key in references[1:]:
        location = locations[key]
        if abs(location - primary) > 1 and location not in seen:
            seen.add(location)
            yield key


def reference_label(quote):
    return f"Dẫn chứng bổ sung · {quote}" if quote else "Dẫn chứng bổ sung"


def render_question(number, spec, article):
    answer = int(article.get("data-answer"))
    choices = [choice.text_content().strip() for choice in article.xpath(
        './div[@class="passage-transcript"]/ol/li'
    )]
    notes = spec["choices"]
    if len(choices) != 4 or len(notes) != 4:
        raise ValueError(f"Question {number} must have four choices")
    scans = article.xpath('ancestor::section[@class="lesson"]/div[@data-pencil-key]/figure/img')
    sizes = [(int(scan.get("width")), int(scan.get("height"))) for scan in scans]

    evidence = {}
    locations = {}
    used_bounds = defaultdict(list)
    prior = (-1, 0)
    for index, group in enumerate(spec["groups"]):
        page = group["page"]
        width, height = sizes[page]
        start, stop = group["rows"]
        if (page, start) < prior or not 0 <= start < stop <= height:
            raise ValueError(f"Question {number} has repeated or out-of-order scan rows")
        prior = (page, stop)
        for mark in group.get("marks", ()):
            key = mark["id"]
            if (key in evidence or mark["tone"] not in TONES or not mark["note"].strip()
                    or not mark["boxes"]):
                raise ValueError(f"Question {number} has invalid evidence {key}")
            if mark["phrase"] not in group["text"]:
                raise ValueError(f"Question {number}: {mark['phrase']} is missing from the source excerpt")
            evidence[key] = mark
            locations[key] = index
            for left, top, right, bottom in mark["boxes"]:
                box = left, top, right, bottom
                if not (0 <= left < right <= width and start <= top < bottom <= stop):
                    raise ValueError(f"Question {number}: {key} extends outside its excerpt")
                if any(intersect(box, other) for other in used_bounds[page]):
                    raise ValueError(f"Question {number}: {key} overlaps another highlight")
                used_bounds[page].append(box)
        for left, top, right, bottom in group.get("frame", ()):
            if not (0 <= left < right <= width and start <= top < bottom <= stop):
                raise ValueError(f"Question {number}: frame mask extends outside its excerpt")
            if any(intersect((left, top, right, bottom), box) for box in used_bounds[page]):
                raise ValueError(f"Question {number}: frame mask obscures a highlight")

    for choice, note in enumerate(notes, 1):
        references = note["evidence"]
        if not references or not all(key in evidence for key in references):
            raise ValueError(f"Question {number}, choice {choice} has no valid evidence")
        if not note["translation"].strip() or not note["reason"].strip():
            raise ValueError(f"Question {number}, choice {choice} is incomplete")

    def target(key):
        return f'evidence-{number}-{key}'

    def render_note(choice, note):
        status = "đúng" if choice == answer else "sai"
        references = note["evidence"]
        anchors = "".join(
            f' <a class="review-reference no-print" href="#{escape(target(key), quote=True)}">'
            f'{escape(reference_label(evidence[key]["phrase"]))}</a>'
            for key in supplementary_refs(references, locations)
        )
        return (
            f'<p class="review-note" data-choice="{choice}" data-verdict="{status}" '
            f'data-evidence="{escape(" ".join(target(ref) for ref in references))}">'
            f'<span class="review-option"><strong>{choice}.</strong> '
            f'<span lang="ja">{escape(choices[choice - 1])}</span> '
            f'<span class="review-translation">{escape(note["translation"])}</span></span>'
            f'<span class="review-explanation">{escape(note["reason"])}{anchors}</span></p>'
        )

    def render_group(group):
        page = group["page"]
        width, height = sizes[page]
        start, stop = group["rows"]
        marks = group.get("marks", ())
        rects = []
        captions = []
        for mark in marks:
            key, tone = mark["id"], mark["tone"]
            # The text cue and every box use the same semantic category.
            captions.append(
                f'<span class="review-cue" id="{target(key)}" data-tone="{tone}">'
                f'{escape(mark["note"])}</span>'
            )
            for left, top, right, bottom in mark["boxes"]:
                rects.append(
                    f'<rect x="{left}" y="{top-start}" width="{right-left}" height="{bottom-top}" '
                    f' rx="1" data-tone="{tone}" data-evidence="{target(key)}"/>'
                )
        caption = f'<p class="review-note review-evidence-caption">{" ".join(captions)}</p>' if captions else ""
        source = group["text"]
        ranges = sorted(((source.index(m["phrase"]), m) for m in marks), key=lambda item: item[0])
        printed = []
        cursor = 0
        for offset, mark in ranges:
            if offset < cursor:
                raise ValueError(f"Question {number}: overlapping source phrases")
            printed.append(escape(source[cursor:offset]))
            printed.append(f'<mark data-tone="{mark["tone"]}">{escape(mark["phrase"])}</mark>')
            cursor = offset + len(mark["phrase"])
        printed.append(escape(source[cursor:]))
        frame = "".join(
            f"M{left} {top-start}h{right-left}v{bottom-top}h-{right-left}Z"
            for left, top, right, bottom in group.get("frame", ())
        )
        frame_cover = (
            f'<svg class="scan-frame-cover" viewBox="0 0 {width} {stop-start}" aria-hidden="true">'
            f'<path d="{frame}"/></svg>' if frame else ""
        )
        return (
            caption +
            f'<div class="review-strip no-print" data-page="{page}" '
            f'style="--ratio:{width} / {stop-start};--shift:{-100*start/height:.6f}%">'
            f'<img alt=""><svg viewBox="0 0 {width} {stop-start}" aria-hidden="true">'
            f'{"".join(rects)}</svg>{frame_cover}</div>'
            f'<p class="review-quote" lang="ja">{"".join(printed)}</p>'
        )

    notes_by_group = defaultdict(list)
    for choice, note in enumerate(notes, 1):
        notes_by_group[locations[note["evidence"][0]]].append(render_note(choice, note))
    result = [
        f'<div class="review-evidence">{"".join(notes_by_group[index])}{render_group(group)}</div>'
        for index, group in enumerate(spec["groups"])
    ]
    return "\n".join(result) + "\n"


def replace_review(page, specs):
    document = html.fromstring(page)
    articles = {int(a.get("id")[2:]): a for a in document.xpath('//article[@data-answer]')}
    rendered = set()

    def replace(match):
        number = match[1]
        if number not in specs:
            return match[0]
        article = articles[int(number)]
        solution = match[0]
        beginning = re.search(r'<div class="(?:review-evidence|review-ordered-notes|q60-map)"', solution)
        start = beginning.start() if beginning else solution.rindex("</details>")
        end = solution.find("<h4>Áp dụng Bí kíp</h4>", start)
        if end < 0:
            end = solution.rindex("</details>")
        rendered.add(number)
        return (
            solution[:start]
            + render_question(number, specs[number], article)
            + solution[end:]
        )

    page = SOLUTION.sub(replace, page)
    if set(specs) != rendered:
        raise ValueError(f"Questions not found: {sorted(set(specs) - rendered)}")
    if 'id="reading-review-style"' not in page:
        page = page.replace("</head>", REVIEW_STYLE + "</head>", 1)
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exam", type=Path)
    parser.add_argument("annotations", type=Path)
    args = parser.parse_args()
    page = args.exam.read_text()
    annotations = json.loads(args.annotations.read_text())
    args.exam.write_text(replace_review(page, annotations))


if __name__ == "__main__":
    main()
