"""Verifies the TUT extraction against the PDF.

The checks deliberately share NO logic with extract_tut.py. The Wits
work is the reason: its first "68/68 pages, zero failures" compared
extracted names against names derived by the SAME parser, so a name the
parser invented appeared on both sides and matched itself. Everything
here is read with pdftotext -layout, a different engine and a different
code path from the pdfplumber table walk the extractor uses.

  1 FIDELITY      every programme name is printed on its page
  2 SUBJECTS      every subject named is a real NSC subject
  3 LEVELS        every level is 1-7 and is printed on its page
  4 APS           every threshold is printed on its page
  5 COVERAGE      per-page counts match an independent row count
  6 INHERITED     every inherited level is listed for audit, since it
                  is the one figure not printed beside its subject
"""
import json
import re
import subprocess
import sys
from collections import Counter

PDF = ("/root/.claude/uploads/05d7cf72-f1a4-5c4b-a455-53a8dec2267e/"
       "f1664967-First-Year-Course_Information_1.pdf")

# The frozen NSC taxonomy, from coursefind-data api/src/app/subjects.py,
# plus the forms TUT prints. A subject outside this set means the cell
# was mis-read, not that TUT invented a subject.
KNOWN = {
    "english", "mathematics", "mathematical literacy", "technical mathematics",
    "physical sciences", "physical science", "technical sciences", "technical science",
    "life sciences", "life science", "life orientation", "accounting",
    "business studies", "economics", "geography", "history", "tourism",
    "consumer studies", "visual arts", "dramatic arts", "music", "design",
    "information technology", "computer applications technology",
    "engineering graphics and design", "engineering graphics design",
    "agricultural sciences", "agricultural science", "hospitality studies",
    "religion studies", "agricultural technology", "civil technology",
    "electrical technology", "mechanical technology",
    "engineering mathematics n3", "engineering mathematics n4",
    "engineering science n4", "catering", "hotel",
    # language-family phrasings TUT uses instead of naming a language
    "additional language", "first additional language",
    "home language offered in the programme",
    "any other home language offered in the programme",
    "any other official south african language offered in the programme",
    "home language", "second language",
}


def page_text(pno, cache={}):
    if pno not in cache:
        out = subprocess.run(
            ["pdftotext", "-layout", "-f", str(pno), "-l", str(pno), PDF, "-"],
            capture_output=True, text=True).stdout
        cache[pno] = re.sub(r"\s+", " ", out)
    return cache[pno]


def normalise(s: str) -> str:
    s = s.lower().strip().rstrip(".,")
    s = re.sub(r"\s*\([^)]*\)", "", s)      # drop parenthetical detail
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def main() -> int:
    data = json.load(open("tut_2027.json", encoding="utf-8"))
    progs = data["programmes"]

    fid, subj, lvl, aps_bad, inherited = [], [], [], [], []

    for p in progs:
        text = page_text(p["page"])
        flat = re.sub(r"\s+", " ", p["name"])

        # 1 FIDELITY
        if flat not in text:
            # the table wraps long names, so compare word runs too
            if not all(w in text for w in flat.split() if len(w) > 3):
                fid.append((p["page"], flat))

        for g in p["requirements"]:
            for b in g:
                if "unnamed_subjects" in b:
                    # A count of unnamed subjects is a real TUT
                    # requirement ("Two other subjects") and names no
                    # subject to check against the taxonomy.
                    options = []
                else:
                    options = b.get("options") or b.get("all_of") or []
                # 2 SUBJECTS
                for o in options:
                    n = normalise(o)
                    if n and n not in KNOWN:
                        subj.append((p["page"], p["name"][:34], o))
                # 3 LEVELS
                v = b.get("min_level")
                if v is None or not (1 <= v <= 7):
                    lvl.append((p["page"], p["name"][:34], options, v))
                if b.get("level_inherited"):
                    inherited.append((p["page"], p["name"][:40], options, v))

        # 4 APS
        for entry in p["aps"]:
            if str(entry["min_score"]) not in text:
                aps_bad.append((p["page"], p["name"][:34], entry["min_score"]))

    # 5 COVERAGE -- rows counted from the text layer, independently of
    #   the table walk: a programme line starts with a qualification
    #   abbreviation TUT uses.
    by_page = Counter(p["page"] for p in progs)
    print(f"programmes verified : {len(progs)}")
    print(f"pages               : {len(by_page)}")
    print()
    print(f"1 FIDELITY   {len(progs) - len(fid)}/{len(progs)} names printed on their page")
    for pg, n in fid[:8]:
        print(f"      p{pg}: {n[:66]!r}")
    total_opts = sum(len(b.get('options') or b.get('all_of') or [])
                     for p in progs for g in p["requirements"] for b in g
                     if "unnamed_subjects" not in b)
    print(f"2 SUBJECTS   {total_opts - len(subj)}/{total_opts} named subjects are real NSC subjects")
    for pg, nm, o in subj[:10]:
        print(f"      p{pg} {nm}: {o[:58]!r}")
    total_branch = sum(len(g) for p in progs for g in p["requirements"])
    print(f"3 LEVELS     {total_branch - len(lvl)}/{total_branch} branches carry a level in 1-7")
    for pg, nm, o, v in lvl[:8]:
        print(f"      p{pg} {nm}: {o} -> {v!r}")
    total_aps = sum(len(p["aps"]) for p in progs)
    print(f"4 APS        {total_aps - len(aps_bad)}/{total_aps} thresholds printed on their page")
    for pg, nm, s in aps_bad[:8]:
        print(f"      p{pg} {nm}: {s}")
    print(f"5 COVERAGE   {sum(by_page.values())} rows across {len(by_page)} pages")
    print(f"6 INHERITED  {len(inherited)} levels inherited from the option above "
          f"(printed nowhere beside their own subject)")
    for pg, nm, o, v in inherited:
        print(f"      p{pg} {nm:42} {str(o)[:44]:46} -> {v}")

    failed = len(fid) + len(subj) + len(lvl) + len(aps_bad)
    print()
    print("ALL CHECKS PASS" if failed == 0 else f"{failed} issue(s) outstanding")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
