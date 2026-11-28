"""Normalize the order and highlight geometry of published reading reviews."""

import argparse
from collections import defaultdict
from pathlib import Path
import re

from lxml import html

from render_reading_review import SOLUTION, intersect


TONES = {"meaning": 0, "grammar": 1, "tip": 2}
CLASS = 'contains(concat(" ", normalize-space(@class), " "), " {} ")'
RATIO = re.compile(r'--ratio:(\d+) / (\d+);--shift:([-.\d]+)%')
STYLE = """
<style id="reading-review-links">
.review-reference { margin-inline-start: .45em; color: #126c60; }
.review-note .review-cue[data-tone] .review-cue-gloss { color: inherit; }
</style>
"""


def source(node):
    return html.tostring(node, encoding="unicode", with_tail=False)


def bounds(rect):
    x, y, w, h = (int(rect.get(key)) for key in ("x", "y", "width", "height"))
    return x, y, x+w, y+h


def difference(box, cover):
    if not intersect(box, cover):
        yield box
        return
    x, y, r, b = box
    lx, ty, rx, by = cover
    left, top, right, bottom = max(x, lx), max(y, ty), min(r, rx), min(b, by)
    for region in ((x, y, r, top), (x, bottom, r, b), (x, top, left, bottom), (right, top, r, bottom)):
        if region[0] < region[2] and region[1] < region[3]:
            yield region


def partition_rectangles(group, notes):
    strip = group.xpath('./div[' + CLASS.format("review-strip") + ']')
    if not strip:
        return
    rects = strip[0].xpath('./svg/rect')
    painted = [rect for rect in rects if rect.get("data-tone") in TONES]
    if not painted and notes:
        # These legacy boxes identify the text cited by the explanation.
        painted = rects
        for rect in painted:
            rect.set("data-tone", "meaning")

    covered = []
    for rect in sorted(painted, key=lambda rect: -TONES[rect.get("data-tone")]):
        original = bounds(rect)
        regions = [original]
        for existing in covered:
            regions = [piece for region in regions for piece in difference(region, existing)]
            if not regions:
                break
        if regions != [original]:
            container = rect.getparent()
            index = container.index(rect)
            container.remove(rect)
            for offset, (left, top, right, bottom) in enumerate(regions):
                clipped = html.Element("rect", attrib=dict(rect.attrib))
                for key, value in zip(("x", "y", "width", "height"), (left, top, right-left, bottom-top)):
                    clipped.set(key, str(value))
                container.insert(index + offset, clipped)
        covered.extend(regions)

    available = {rect.get("data-tone") for rect in painted}
    if available:
        for note in notes:
            for cue in note.xpath('.//*[@data-tone]'):
                if cue.get("data-tone") not in available:
                    del cue.attrib["data-tone"]


def trim_adjacent_overlap(groups, scan_heights):
    previous = None
    for group in groups:
        for strip in group.xpath('./div[' + CLASS.format("review-strip") + ']'):
            ratio = RATIO.fullmatch(strip.get("style", ""))
            if ratio is None:
                continue
            page = int(strip.get("data-page"))
            width, length = int(ratio[1]), int(ratio[2])
            top = round(-float(ratio[3]) * scan_heights[page] / 100)
            if previous is not None:
                last, prior_page, prior_top, prior_length = previous
                overlap = prior_top+prior_length-top
                if page == prior_page and 0 < overlap <= 2 and prior_top < top:
                    new_length = prior_length-overlap
                    last.set("style", last.get("style").replace(f' / {prior_length};', f' / {new_length};', 1))
                    for svg in last.xpath('./svg'):
                        svg.set("viewbox", f'0 0 {width} {new_length}')
                        for rect in svg.xpath('./rect'):
                            y = int(rect.get("y"))
                            if y >= new_length:
                                svg.remove(rect)
                            elif y+int(rect.get("height")) > new_length:
                                rect.set("height", str(new_length-y))
            previous = strip, page, top, length


def place_ordered_notes(groups, notes_by_group, question):
    seen = 0
    pending = []
    for group in groups:
        if not pending:
            first = group
        pending.extend((group, note) for note in notes_by_group[group])
        if any(int(note.get("data-choice")) > seen+len(pending) for _, note in pending):
            continue
        moved = any(original is not first for original, _ in pending)
        if moved:
            summary = html.Element("div", {"class": "review-ordered-notes"})
            first.addprevious(summary)
            for original, note in sorted(pending, key=lambda entry: int(entry[1].get("data-choice"))):
                for prior in note.xpath('.//a[' + CLASS.format("review-reference") + ']'):
                    prior.getparent().remove(prior)
                anchor = html.Element("a", href=f'#{original.get("id")}')
                anchor.set("class", "review-reference no-print")
                anchor.text = "Dẫn chứng"
                explanation = note.xpath('./span[@class="review-explanation"]')
                (explanation[0] if explanation else note).append(anchor)
                summary.append(note)
        else:
            for _, note in reversed(sorted(pending, key=lambda entry: int(entry[1].get("data-choice")))):
                first.insert(0, note)
        seen += len(pending)
        pending = []
    if pending:
        raise ValueError(f"Cannot order the explanations for question {question}")


def normalize_review(original, number, scan_heights):
    solution = html.fromstring(original)
    model = solution.xpath('./div[@class="q60-map"]')
    container = model[0] if model else solution
    groups = container.xpath('./div[' + CLASS.format("review-evidence") + ']')
    if not groups or container.xpath('./div[@class="review-ordered-notes"]'):
        return original
    notes_by_group = {group: group.xpath('./p[@data-choice]') for group in groups}
    notes = [note for group in groups for note in notes_by_group[group]]
    if sorted(int(note.get("data-choice")) for note in notes) != [1, 2, 3, 4]:
        return original
    if any(note.get("data-evidence") for note in notes):
        return original

    trim_adjacent_overlap(groups, scan_heights)
    for index, group in enumerate(groups, 1):
        if notes_by_group[group] and not group.get("id"):
            group.set("id", f'evidence-{number}-line-{index}')
        for note in notes_by_group[group]:
            note.set("data-evidence", group.get("id"))
        partition_rectangles(group, notes_by_group[group])
    place_ordered_notes(groups, notes_by_group, number)

    first = re.search(r'<div class="(?:review-evidence|q60-map)\b', original).start()
    suffix = original.find("<h4>Áp dụng Bí kíp</h4>", first)
    if suffix < 0:
        suffix = original.rindex("</details>")
    if model:
        updated = source(container)
    else:
        updated = "\n".join(source(node) for node in solution.xpath(
            './div[' + CLASS.format("review-evidence") + ' or @class="review-ordered-notes"]'
        ))
    updated = updated.replace("viewbox=", "viewBox=")
    updated = re.sub(r"<(rect|path)([^>]*)></\1>", r"<\1\2/>", updated)
    return original[:first] + updated + "\n" + original[suffix:]


def normalize(page):
    document = html.fromstring(page)
    scans = {}
    for lesson in document.xpath('//section[@class="lesson"]'):
        heights = [int(im.get("height")) for im in lesson.xpath('./div[@data-pencil-key]/figure/img')]
        for article in lesson.xpath('./article[@data-answer]'):
            scans[article.get("id")[2:]] = heights
    updated = SOLUTION.sub(lambda match: normalize_review(match[0], match[1], scans[match[1]]), page)
    if updated != page and 'id="reading-review-links"' not in updated:
        updated = updated.replace("</head>", STYLE + "</head>", 1)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exams", metavar="EXAM", type=Path, nargs="+")
    args = parser.parse_args()
    for exam in args.exams:
        current = exam.read_text()
        updated = normalize(current)
        if current != updated:
            exam.write_text(updated)


if __name__ == "__main__":
    main()
