"""Reads one programme row's COMPULSORY SUBJECTS and MINIMUM LEVEL
columns into structured requirements.

WHY THIS READS COORDINATES AND NOT CELL TEXT
---------------------------------------------
extract() hands back each column as a newline-joined string, so pairing
subjects with levels means zipping two lists and trusting they are the
same length. They are not. Page 14's Dip (Administrative Information
Management) prints

    English                                   4
    Mathematics or Technical Mathematics or   3
    Mathematical Literacy

-- three subject lines, two levels, because the source simply does not
print a minimum for Mathematical Literacy on that row, while the two
rows directly beneath it do. Zipping shifts every later pairing by one
and reports a level the document never printed. The level is set
beside its subject on the same baseline, so the pairing is a y
comparison, and a missing one stays missing.

THE FOUR LINE KINDS
    requirement   a subject line with a level beside it
    alternative   a line introduced by a preceding "or"/"and/or"; it is
                  a new branch even when its level is absent
    wrap          a line with no level whose predecessor did NOT end in
                  a connector -- the text simply ran on
                  ("Any other home language offered in the" +
                  "programme")
    header/prose  a line ending in ":" introducing a combination, or a
                  sentence that is a note rather than a requirement
                  ("Preference will be given to applicants with ...")
"""
import re

Y_TOL = 3.0

# NSC subject names that contain "and" and must never be split on it.
ATOMIC = ("engineering graphics and design",)

# A requirement for a NUMBER of unnamed subjects rather than a named
# one: "Any three additional subjects", "Two other subjects", "Any
# other additional language".
UNNAMED = re.compile(
    r"^(any|two|three|four|a|an)\b.*\b(subjects?|languages?)\b", re.I)


def split_outside_parens(text: str, word: str) -> list[str]:
    """Splits on a connector only at bracket depth zero, so a
    parenthetical listing trades with "and" or "or" stays whole."""
    parts, depth, buf, i = [], 0, [], 0
    token = re.compile(rf"\s+{word}\s+", re.I)
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0:
            m = token.match(text, i)
            if m:
                parts.append("".join(buf))
                buf = []
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]
CONNECTOR_END = re.compile(r"\b(and/or|or)\s*$", re.I)
HEADER_END = re.compile(r":\s*$")
# A requirement names subjects; these are sentences about the applicant.
PROSE = re.compile(
    r"\b(preference will be given|applicants? (are|must|who)|proof of|"
    r"years.{0,3} (of )?(confirmed )?(relevant )?work|experience|"
    r"should be submitted|in the form of|employed in|qualification in the)\b",
    re.I)


def column_lines(page, cell, row_top, row_bottom, words):
    """Text lines inside one cell, each with the y of its baseline."""
    buckets: dict[float, list] = {}
    for w in words:
        if cell[0] <= w["x0"] < cell[2] and row_top <= w["top"] < row_bottom:
            key = next((k for k in buckets if abs(k - w["top"]) <= Y_TOL), w["top"])
            buckets.setdefault(key, []).append(w)
    out = []
    for y in sorted(buckets):
        ws = sorted(buckets[y], key=lambda w: w["x0"])
        out.append((y, " ".join(w["text"] for w in ws).strip()))
    return out


def level_at(y, levels):
    for ly, value in levels:
        if abs(ly - y) <= Y_TOL:
            return value
    return None


def parse(page, extent, cols, words):
    """-> (groups, notes, problems)

    groups is a list of requirement groups; each group is a list of
    branches, and a learner satisfies the group by satisfying ANY one
    branch. A branch is {"options": [...], "min_level": int|None}: its
    options are interchangeable AT THAT LEVEL ("Mathematics or
    Technical Mathematics"), and `all_of` marks the "X and Y" form.
    """
    top, bottom = extent
    subject_lines = column_lines(page, cols["subjects"], top, bottom, words)
    level_lines = column_lines(page, cols["levels"], top, bottom, words)
    levels = [(y, int(m.group())) for y, t in level_lines
              if (m := re.match(r"\d+", t))]

    notes, problems = [], []
    # 1. fold wraps into the line they continue
    folded: list[tuple[float, str, int | None]] = []
    for y, text in subject_lines:
        lvl = level_at(y, levels)
        # A line ending in ":" heads the lines below it and is never a
        # continuation of the line above, however it looks. Folding it
        # produced the subject "Mathematical Literacy One of the
        # following combinations:" on page 9.
        if folded and lvl is None and not HEADER_END.search(text) \
                and not CONNECTOR_END.search(folded[-1][1]) \
                and not HEADER_END.search(folded[-1][1]) and not PROSE.search(text):
            py, ptext, plvl = folded[-1]
            folded[-1] = (py, f"{ptext} {text}", plvl)
            continue
        folded.append((y, text, lvl))

    # 2. prose and headers out of the requirement stream
    kept: list[tuple[str, int | None]] = []
    for _y, text, lvl in folded:
        if PROSE.search(text) and lvl is None:
            notes.append(text)
            continue
        if HEADER_END.search(text) and lvl is None:
            notes.append(text)
            continue
        kept.append((text, lvl))

    # 3. group by the connector that ends each line
    groups, current = [], []
    for text, lvl in kept:
        body = CONNECTOR_END.sub("", text).strip().rstrip(",.")
        options = [o.strip() for o in split_outside_parens(body, "or") if o.strip()]
        branch = {"options": options, "min_level": lvl}

        # "Any three additional subjects", "Two other subjects" -- a
        # COUNT of unnamed subjects, not a subject. Naming it as one
        # produced the subject "Two other subjects", which matches
        # nothing on any certificate.
        if len(options) == 1 and UNNAMED.match(options[0]):
            branch = {"unnamed_subjects": options[0], "min_level": lvl}
        elif len(options) == 1 and re.search(r"\band\b", body, re.I):
            # "Life Sciences and Physical Science" -- both, not either.
            # Split outside brackets only: "Mechanical Technology
            # (Automotive/Fitting and Machining/Welding and Metal
            # Work)" is ONE subject whose bracket happens to contain
            # "and", and splitting it invented three subjects. So does
            # splitting "Engineering Graphics and Design", which is one
            # NSC subject -- hence ATOMIC below.
            if not any(a in body.lower() for a in ATOMIC):
                parts = [p.strip() for p in split_outside_parens(body, "and") if p.strip()]
                if len(parts) > 1:
                    branch = {"all_of": parts, "min_level": lvl}
        current.append(branch)
        if not CONNECTOR_END.search(text):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    # 4. an alternative with no printed level inherits the last one
    #    printed in its own block.
    #
    #    The table is set "print on change": a number appears beside an
    #    alternative only where its requirement DIVERGES from the
    #    option above it. Page 14 shows both halves of the convention
    #    on adjacent rows --
    #
    #      Dip (Adventure Tourism)         Dip (Administrative Info Mgmt)
    #        English                 4       English                 4
    #        Mathematics or Tech ... 3       Mathematics or Tech ... 3
    #        Mathematical Literacy   4       Mathematical Literacy
    #
    #    -- the first prints 4 because Maths Literacy is held to a
    #    higher level than Mathematics, the second prints nothing
    #    because it is held to the same 3.
    #
    #    Inheritance is scoped to the BLOCK, never across one: a new
    #    requirement that opens with no level has nothing legitimate to
    #    inherit, so it is still reported rather than silently given
    #    the level of an unrelated subject above it.
    for g in groups:
        carried = None
        for b in g:
            if b["min_level"] is None:
                if carried is None:
                    problems.append(
                        "no printed level and nothing to inherit for "
                        f"{b.get('options') or b.get('all_of')}")
                else:
                    b["min_level"] = carried
                    b["level_inherited"] = True
            else:
                carried = b["min_level"]
    return groups, notes, problems
