"""Delivery protocol: slice-and-emit, instead of read-everything-then-write.

Every generation failure on a large source died inside section 3, and the two
completed staged runs differed most in where they spent the front matter: the
successful one reached its first subsection at line 130, the failed one at 482.
That points at reading rather than writing as the consumer of budget. Both prior
delivery shapes -- one big write, and read the whole file then append -- require
the read to finish before any writing starts, so whatever the read costs is
purely lost.

Slice-and-emit interleaves them: take the inventory cheaply, then for each group
of subprograms read only that group's source region and immediately write that
group's subsection. Section 1, 2 and the summary sections go last, built from
what section 3 already says, which also means they cost nothing extra to read for.

Tested as a prompt-level protocol first. It only goes into the skill if it works,
because three previous additions to this project were not shown to help and two of
them had to be rolled back.
"""
import io
import os
import sys

OUT = sys.argv[1]

PROTOCOL = """\
DELIVERY PROTOCOL -- slice and emit. Follow this instead of reading the file
end-to-end first. It exists because 9 of 12 generation attempts on this file
produced a truncated report or no file, and the ones that failed died inside
section 3, which is where the reading has to have been spent.

Do NOT read the whole source before writing anything.

  Step A  Inventory, cheaply. Grep the source for the lines that open each
          subprogram -- METHOD, FORM, FUNCTION, CLASS, INTERFACE -- and note each
          one's line number. That is your table of contents. Do not read bodies yet.

  Step B  Sections one and two from the inventory plus the interface / declaration
          section only. Do not read method bodies for this.

  Step C  Then work through section 3 in groups of at most four subprograms. For
          each group: read ONLY those subprograms' source lines, using the line
          numbers from step A, then immediately append that group's subsections to
          the report before touching the next group.

  Step D  Only when section 3 is complete, append sections four, five and six.
          Build them from what section 3 already says. Do not re-read the source.

Rules that matter:
  - Never hold the whole source in view at once. Read a region, write its analysis,
    move on.
  - Append after every group, so a partial file is always a valid prefix.
  - Report which group you are on if you need to stop.
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
io.open(OUT, "w", encoding="utf-8").write(PROTOCOL)
print(f"wrote {OUT}  ({len(PROTOCOL)} chars)")
print()
print(PROTOCOL)