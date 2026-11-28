"""Align published reading notes with their evidence and normalize highlights."""

import argparse
from collections import defaultdict
from pathlib import Path
import re

from lxml import html

from render_reading_review import SOLUTION, intersect, reference_label, supplementary_refs


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


def place_notes(groups, notes):
    locations = {
        node.get("id"): index
        for index, group in enumerate(groups)
        for node in group.iter()
        if node.get("id")
    }
    notes_by_group = defaultdict(list)
    for note in notes:
        references = note.get("data-evidence").split()
        notes_by_group[locations[references[0]]].append(note)
        for prior in note.xpath('.//a[' + CLASS.format("review-reference") + ']'):
            prior.drop_tree()
        explanation = note.xpath('./span[@class="review-explanation"]')
        for key in supplementary_refs(references, locations):
            source_quotes = groups[locations[key]].xpath('./p[@class="review-quote"]')
            quote = source_quotes[0].text_content().strip() if source_quotes else ""
            if len(quote) > 26:
                quote = quote[:25] + "…"
            anchor = html.Element("a", href=f"#{key}")
            anchor.set("class", "review-reference no-print")
            anchor.text = reference_label(quote)
            (explanation[-1] if explanation else note).append(anchor)
    for index, local_notes in notes_by_group.items():
        group = groups[index]
        for note in sorted(local_notes, key=lambda entry: int(entry.get("data-choice")), reverse=True):
            group.insert(0, note)


def normalize_review(original, number, scan_heights):
    solution = html.fromstring(original)
    model = solution.xpath('./div[@class="q60-map"]')
    container = model[0] if model else solution
    groups = container.xpath('./div[' + CLASS.format("review-evidence") + ']')
    if not groups:
        return original
    summaries = container.xpath('./div[@class="review-ordered-notes"]')
    notes = container.xpath('./div/p[@data-choice]')
    if sorted(int(note.get("data-choice")) for note in notes) != [1, 2, 3, 4]:
        return original
    has_references = all(note.get("data-evidence") for note in notes)
    if has_references and not summaries:
        return original

    if not has_references:
        trim_adjacent_overlap(groups, scan_heights)
        for index, group in enumerate(groups, 1):
            local_notes = group.xpath('./p[@data-choice]')
            if local_notes and not group.get("id"):
                group.set("id", f'evidence-{number}-line-{index}')
            for note in local_notes:
                note.set("data-evidence", group.get("id"))
            partition_rectangles(group, local_notes)
    place_notes(groups, notes)
    for summary in summaries:
        summary.drop_tree()

    first = re.search(r'<div class="(?:review-evidence|review-ordered-notes|q60-map)\b', original).start()
    suffix = original.find("<h4>Áp dụng Bí kíp</h4>", first)
    if suffix < 0:
        suffix = original.rindex("</details>")
    if model:
        updated = source(container)
    else:
        updated = "\n".join(source(group) for group in groups)
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
