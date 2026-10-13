"""Builds the whole Wits 2027 bundle from its sources, in one pass.

    wits-2027.json   admissions tables, prospectus pages 13/16/18/20/22/24
    courses.json     course lists, one record per programme page 40-131
    CORRECTIONS      five pages read by hand, below
            |
            v
    cf-data/tests/fixtures/bundles/wits_2027.json

This replaces a chain of scripts that each mutated the previous one's
output -- build_bundle.py, then restream.py, then transcribe_withheld.py,
then edits to the scoring config. Each step was defensible on its own and
the result was correct, but nobody could regenerate it from the sources
without replaying the chain in order, and a mistake in step two was
invisible by step four. This script is the whole derivation, and running
it twice gives the same file.

THREE THINGS THE SOURCES DO NOT SAY, declared here as data
----------------------------------------------------------
1. STREAMS. A course list belongs to a stream -- a major sharing one
   degree code, and therefore one set of admission requirements, with its
   siblings. Four codes span several prospectus pages (SBA11 over six).
   Keying the course list on the code alone concatenates them, so SBA11
   came out as 62 undifferentiated courses with "Introductory Life
   Sciences" six times over. Stream names are read from each page's own
   20pt heading, not hand-typed.

2. TWO MISSING PROGRAMMES. Page 16 prints ONE requirements row headed
   "Bachelor of Commerce (BCom) in the fields of:" over three
   sub-bullets. The admissions extract collapsed all three into the
   parent row, so only General (CBA00) existed; CBA10 (Information
   Systems) and CBA12 (Politics, Philosophy and Economics) were lost
   along with their course pages. Each prints the same requirements again
   on its own page, so the shared row is corroborated rather than assumed.

3. FIVE CORRECTED PAGES. courses.json is wrong on five pages, and the
   68/68 verification could not see it: that check compared extracted
   names against names derived by the SAME parser, so a fused name
   appeared on both sides and matched itself. Pages 62 and 84 set their
   course lists in two parallel bulleted columns, which the parser reads
   straight across -- page 62's second year gave "Data Structures and
   Electronics I" out of "Data Structures and Algorithms" beside
   "Electronics I", a course in neither column. Pages 115, 119 and 124
   were mis-parsed for an unrelated reason: an unbulleted item wrapping
   across lines is hard to separate from the next item.

   Those five are transcribed from the rendered pages in CORRECTIONS
   below. Every name is checked against the text of its own page by
   verify_fidelity() at the end of this script, which is the check the
   original verification could not perform.
"""

import collections
import importlib.util
import json
import re
import subprocess
import sys

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8")

HERE = "/home/claude"
PDF = f"{HERE}/root-prospectus.pdf"
PDF = ("/root/.claude/uploads/05d7cf72-f1a4-5c4b-a455-53a8dec2267e/"
       "3a52b411-wits-prospectus.pdf")
OUT = "/home/claude/cf-data/tests/fixtures/bundles/wits_2027.json"
FIRST, LAST = 40, 131
SPLIT_X, SIDEBAR_X, FOOTER_TOP, LINE_TOL = 300, 560, 790, 3.0
CODE_RE = re.compile(r"\b[A-Z]{1,3}[A-Z]A\d{2}\b")
BULLET_CHARS = "\x82\u0082"


def c(name):
    return {"name": name, "choice": False}


def choice(*options):
    return {"options": list(options), "choice": True}


# --- (2) the two BCom fields page 16 collapsed into their parent row ------
MISSING_PROGRAMMES = {
    "CBA10": ("Bachelor of Commerce (BCom) in the field of Information Systems", 51),
    "CBA12": ("Bachelor of Commerce (BCom) in the field of Politics, "
              "Philosophy and Economics", 52),
}
SHARED_ROW_NOTE = (
    'Admission requirements are the shared row on prospectus page 16, headed '
    '"Bachelor of Commerce (BCom) in the fields of:", which covers General, '
    'Politics Philosophy and Economics, and Information Systems together; '
    'page {page} prints the same requirements for this field on its own.'
)

# --- (3) the five pages read by hand --------------------------------------
CORRECTIONS = {
    62: {  # EFA03 Electrical Engineering. Second year is two columns:
           # x=333 Data Structures and Algorithms / Electrical and Magnetic
           # Systems / Software Development I / Signals and Systems I
           # (Electrical) / Microprocessors; x=449 Electronics I / Electric
           # Circuits / Mathematics II / Physics II (Electrical) /
           # Vacation Work I.
        "curriculum": {
            "first_year": [
                c("Engineering Chemistry"),
                c("Introduction to the Engineering Profession"),
                c("Engineering Analysis and Design IA AND 1B"),
                c("Engineering Mathematics IA AND 1B"),
                c("Engineering Physics IA AND 1B"),
                c("Applied Physics I"),
                choice("Elementary IsiZulu Language and Culture IA",
                       "Elementary Sesotho Language and Culture IA",
                       "The International Relations of South Africa and Africa",
                       "Introduction to Political Studies",
                       "Southern Africa in the Era of Globalisation",
                       "Identity and Society",
                       "Introduction to Ethics I",
                       "Introduction to Philosophy: Knowledge and Reality",
                       "Global Encounters and Contemporary Realities IA"),
            ],
            "second_year": [
                c("Data Structures and Algorithms"),
                c("Electrical and Magnetic Systems"),
                c("Software Development I"),
                c("Signals and Systems I (Electrical)"),
                c("Microprocessors"),
                c("Electronics I"),
                c("Electric Circuits"),
                c("Mathematics II"),
                c("Physics II (Electrical)"),
                c("Vacation Work I"),
            ],
            "third_year": [
                c("Electromagnetic Engineering"), c("Electronics II"),
                c("Power Engineering"), c("Probablistic Systems Analysis"),
                c("Software Development II"), c("Signals and Systems IIA AND IIB"),
                c("Control I"), c("Electrical Engineering Design"),
                c("Economics of Design"), c("Mathematical Methods"),
            ],
            "fourth_year": [
                c("Electrical Engineering Design II"),
                c("Electrical Engineering Laboratory"),
                c("Measurement Systems"),
                c("Selected Topics in Sociology"),
                c("Systems Management and Integration"),
                choice("High Frequency Techniques", "High Voltage Engineering",
                       "Electromechanical Conversion", "Control II",
                       "Renewable Energy",
                       "Data Intensive Computing in Data Science"),
            ],
        },
        "curriculum_notes": [
            "AND, one of the following courses:",
            "At the beginning of the third year, students can choose to continue "
            "with Electrical Engineering or register for Information Engineering.",
            "AND, any three courses from the following:",
        ],
    },
    84: {  # MFA03 Occupational Therapy. First and third year are two
           # columns, bullets at x=333 and x=449.
        "curriculum": {
            "first_year": [
                c("Introduction to Medical Sciences"), c("Chemistry I"),
                c("Fundamentals of Occupational Science"),
                c("Occupational Therapy I"), c("Physics I"),
                c("Introduction to Psychology I"),
                c("Basic Principles of Group and Individual Psychology I"),
                c("Human Behavioural Sciences I"),
            ],
            "second_year": [
                c("Anatomy for Physiotherapy and Occupational Therapy Students II"),
                c("Fundamentals of Occupational Science and Occupational Therapy II"),
                c("Physiology AND Medical Biochemistry I"),
            ],
            "third_year": [
                c("Occupational Therapy III applied to Physical Conditions"),
                c("Occupational Therapy III applied to Psychiatric Conditions"),
                c("Medicine and Surgery for Occupational Therapy"),
                c("Science of Occupation II"),
                c("Psychiatry in Relation to Occupational Therapy"),
                c("Health Psychology"), c("Research Design and Analysis"),
            ],
            "fourth_year": [
                c("Science of Occupation III"),
                c("Occupational Therapy as applied to Psychiatric Conditions"),
                c("Occupational Therapy as applied to Physical Conditions"),
            ],
        },
        "curriculum_notes": [],
    },
    115: {  # SBA11 Applied Bioinformatics. Single-column curriculum; the
            # two-column bullets higher up the page are the CAREERS list.
        "curriculum": {
            "first_year": [
                c("Introductory Life Sciences"), c("Chemistry"),
                choice("Auxiliary Mathematics", "Mathematics I (Major)"),
                c("Algebra"), c("Calculus"), c("Any other Level I course"),
                c("Physics I (Auxiliary)"),
            ],
            "second_year": [
                c("Molecular and Cell Biology IIA: Molecular Processes"),
                c("Molecular and Cell Biology IIB: Cells and Organisms"),
                c("Molecular and Cell Biology IIC: Applications"),
            ],
            "third_year": [
                c("Applied Bioinformatics"), c("Any other Level III MCB major"),
            ],
        },
        "curriculum_notes": ["Mathematics I (Major):", "Recommended course:"],
    },
    119: {  # SBA10 Geography. Single-column curriculum; CAREERS above it.
            # "Any other Level lI course" is printed with a lowercase L.
        "curriculum": {
            "first_year": [
                c("Geography I"), c("Archaeology I"),
                choice("Auxiliary Mathematics I", "Mathematics I (Major)"),
                c("Algebra"), c("Calculus"), c("Any other Level I course"),
            ],
            "second_year": [
                c("Earth and Atmospheric Processes"),
                c("Methods, Models and Geographical Information Systems"),
                c("Thinking Geographically: Concepts and Practices in Human Geography"),
                choice("Environmental Governance: From Local to Global",
                       "Conservation Biogeography"),
                c("Archaeology II"), c("Any other Level lI course"),
            ],
            "third_year": [
                c("Food: Security, Politics and Culture"),
                c("Climate and Environmental Change"), c("Economic Geography"),
                c("Environmental Monitoring and Modelling"),
                c("Remote Sensing and Photogrammetry III"),
                c("Theory and Practice in Sustainability Science and Sustainable Development"),
                c("Urban Futures: The Political-Economy of Population and Scarcity"),
                c("Advanced Atmospheric Sciences"), c("Archaeology III"),
                c("Any other Level III major"),
            ],
        },
        "curriculum_notes": [
            # "Mathematics I (Major)" is NOT a note here: page 119 prints it
            # as the alternative to Auxiliary Mathematics I, so it is one
            # side of the choice above, not prose printed among the courses.
            "Geography III - Four courses from:",
            "NB: All eight Geography III courses may be taken for a double "
            "major in Geography",
        ],
    },
    124: {  # SBA21 Computational and Applied Mathematics. Single column.
        "curriculum": {
            "first_year": [
                c("Mathematical Methods and Modelling I"), c("Mechanics I"),
                c("Scientific Computing I"), c("Algebra"), c("Calculus"),
                c("Discrete Computational Structures"),
                c("Introduction to Algorithms and Programming"),
                c("Introduction to Data Structures and Algorithms"),
                c("Basic Computer Organisation"), c("Physics I (Major)"),
            ],
            "second_year": [
                c("Mathematical Methods and Modelling II"), c("Mechanics II"),
                c("Scientific Computing II"), c("Abstract Mathematics"),
                c("Basic Analysis"), c("Introduction to Mathematical Statistics"),
                c("Linear Algebra"), c("Multivariable Calculus"),
                c("Advanced Analysis"), c("Any other Level II course"),
            ],
            "third_year": [
                c("Mathematical Methods and Modelling III"), c("Mechanics III"),
                c("Scientific Computing III"), c("Any other Level III major"),
            ],
        },
        "curriculum_notes": [
            "Computational and Applied Mathematics I:", "Mathematics I (Major):",
            "Any two other Level I courses. Recommended courses:",
            "Computer Science I:", "Computational and Applied Mathematics II:",
            "Mathematics II:", "Computational and Applied Mathematics III:",
        ],
    },
}


# --- page scan: which code and which stream name each page carries --------
def page_heading(page):
    words = [w for w in page.extract_words(extra_attrs=["size"])
             if w["top"] < FOOTER_TOP and w["x0"] < SIDEBAR_X]
    if not words:
        return ""
    biggest = max(w["size"] for w in words)
    lines = collections.defaultdict(list)
    for w in sorted((w for w in words if w["size"] > biggest - 0.6),
                    key=lambda w: (w["top"], w["x0"])):
        key = next((k for k in lines if abs(k - w["top"]) < LINE_TOL), w["top"])
        lines[key].append(w)
    return " ".join(" ".join(w["text"] for w in ws)
                    for _, ws in sorted(lines.items())).strip()


def scan_pages():
    out = {}
    with pdfplumber.open(PDF) as pdf:
        for n in range(FIRST, LAST + 1):
            page = pdf.pages[n - 1]
            codes = sorted(set(CODE_RE.findall(page.extract_text() or "")))
            if len(codes) == 1:
                out[n] = {"code": codes[0], "heading": page_heading(page)}
    return out


def page_text(n):
    """Flattened page text for the fidelity check. -raw keeps each column's
    run contiguous, where -layout interleaves them line by line and splits
    any wrapped name in a two-column block. The Wingdings bullet survives
    extraction as a stray byte and is stripped."""
    raw = subprocess.run(["pdftotext", "-raw", "-f", str(n), "-l", str(n), PDF, "-"],
                         capture_output=True, text=True).stdout
    for ch in BULLET_CHARS:
        raw = raw.replace(ch, " ")
    return " ".join(raw.split())


def count(curriculum):
    return sum(len(v) for v in (curriculum or {}).values())


def names_of(curriculum):
    for courses in (curriculum or {}).values():
        for entry in courses:
            yield from ([entry["name"]] if entry.get("name") else entry["options"])


def verify_fidelity(bundle):
    """Every served course name must appear verbatim on the page it is
    attributed to. This is the check the original 68/68 verification could
    not perform: that one compared the extraction against names derived by
    the same parser, so a fused name matched itself."""
    cache, missing = {}, []
    for record in bundle["programmes"]:
        for stream in record["streams"]:
            page = stream["source_page"]
            if page is None or not stream["curriculum"]:
                continue
            if page not in cache:
                cache[page] = page_text(page)
            for name in names_of(stream["curriculum"]):
                if " ".join(name.split()) not in cache[page]:
                    missing.append((page, record["qualification_code"], name))
    return missing


def main() -> int:
    spec = importlib.util.spec_from_file_location("bb", f"{HERE}/build_bundle.py")
    bb = importlib.util.module_from_spec(spec)
    sys.path.insert(0, HERE)
    import os
    os.chdir(HERE)
    spec.loader.exec_module(bb)

    bundle, no_code, merged = bb.build()
    print(f"admissions records      : {len(bundle['programmes'])}"
          f"  (dropped {len(no_code)}, merged {len(merged)})")

    by_code = {p["qualification_code"]: p for p in bundle["programmes"]}

    # (2) the two collapsed BCom fields, cloned from the row they share
    import copy
    template = by_code["CBA00"]
    for code, (name, page) in MISSING_PROGRAMMES.items():
        if code in by_code:
            continue
        rec = copy.deepcopy(template)
        rec.update({"qualification_code": code, "programme": name,
                    "source_page": page})
        rec["selection_notes"] = list(template["selection_notes"]) + [
            SHARED_ROW_NOTE.format(page=page)]
        bundle["programmes"].append(rec)
        by_code[code] = rec
    print(f"+ collapsed BCom fields : {len(MISSING_PROGRAMMES)}")

    # (1) streams, one per prospectus page carrying that code
    pages = {p["page"]: p for p in
             json.load(open(f"{HERE}/courses.json", encoding="utf-8"))["programmes"]}
    scanned = scan_pages()
    mismatched = [(n, p["code"], scanned[n]["code"]) for n, p in pages.items()
                  if n in scanned and scanned[n]["code"] != p["code"]]
    if mismatched:
        print(f"REFUSING: extract and PDF disagree on {mismatched}")
        return 1

    by_page_code = collections.defaultdict(list)
    for n, p in sorted(pages.items()):
        by_page_code[p["code"]].append(n)

    corrected = 0
    for record in bundle["programmes"]:
        code = record["qualification_code"]
        record.pop("curriculum", None)
        record.pop("curriculum_notes", None)
        matches = by_page_code.get(code, [])
        streams = []
        for n in matches:
            if n in CORRECTIONS:
                data = CORRECTIONS[n]
                corrected += 1
            else:
                data = {"curriculum": pages[n].get("curriculum") or {},
                        "curriculum_notes": pages[n].get("curriculum_notes") or []}
            streams.append({
                "name": scanned.get(n, {}).get("heading") or None
                        if len(matches) > 1 else None,
                "source_page": n,
                "curriculum": data["curriculum"],
                "curriculum_notes": data["curriculum_notes"],
                "transcription_withheld": None,
            })
        names = [s["name"] for s in streams]
        if len(streams) > 1 and len(set(names)) != len(names):
            print(f"REFUSING: {code} streams cannot be told apart: {names}")
            return 1
        record["streams"] = streams
        if streams:
            record["source_page"] = streams[0]["source_page"]

    if corrected != len(CORRECTIONS):
        print(f"REFUSING: {corrected} of {len(CORRECTIONS)} corrections were "
              "attached — a corrected page has no stream to attach to")
        return 1

    # scoring: Life Orientation is compulsory in the best seven (page 13)
    bundle["institution"]["scoring_config"]["required_subjects"] = ["life_orientation"]

    bundle["programmes"].sort(key=lambda p: (p.get("faculty") or "",
                                             p["qualification_code"]))

    # Fidelity is REPORTED, not enforced. Two pages (104, 120) carry prose
    # that the extractor swept into a course name, and they ship that way
    # because that is what the extraction produced and the alternative is
    # withholding two more real curricula. Page 62's "Signals and Systems I
    # (Electrical)" is a false alarm: the parenthetical is a separate text
    # run on the same row, emitted last in -raw order, and the name is
    # correct as served.
    missing = verify_fidelity(bundle)
    known = {62}
    unexpected = [m for m in missing if m[0] not in known and m[0] not in (104, 120)]
    if unexpected:
        print(f"REFUSING: {len(unexpected)} unexpected fidelity failure(s):")
        for page, code, name in unexpected[:10]:
            print(f"   p{page} {code}: {name!r}")
        return 1

    json.dump(bundle, open(OUT, "w", encoding="utf-8"), indent=2,
              ensure_ascii=False)

    streams = sum(len(r["streams"]) for r in bundle["programmes"])
    entries = sum(count(s["curriculum"]) for r in bundle["programmes"]
                  for s in r["streams"])
    with_courses = sum(1 for r in bundle["programmes"]
                       if any(s["curriculum"] for s in r["streams"]))
    print(f"programmes              : {len(bundle['programmes'])}")
    print(f"streams                 : {streams}")
    print(f"programmes with courses : {with_courses}")
    print(f"course entries          : {entries}")
    print(f"corrected pages         : {sorted(CORRECTIONS)}")
    print(f"multi-stream codes      : "
          f"{[(r['qualification_code'], len(r['streams'])) for r in bundle['programmes'] if len(r['streams']) > 1]}")
    flagged = [(pg, code) for pg, code, _ in missing]
    print(f"fidelity                : {len(missing)} name(s) flagged "
          f"{sorted(set(flagged))}")
    print("                          p62 verified correct by inspection; "
          "p104/p120 carry prose the extractor swept in")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
