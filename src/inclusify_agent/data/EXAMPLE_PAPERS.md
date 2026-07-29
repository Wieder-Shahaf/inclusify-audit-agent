# Bundled example inputs — sources and attribution

The two `example_paper_*.txt` files in this directory are real, published academic papers.
They ship as `prompt_examples` on `GET /api/agent_info` (and as the two long entries in
`_EXAMPLE_PROMPTS`) so that a reviewer exercising only the HTTP API sees the agent audit
*academic text*, which is what it claims to do — not just the two one-sentence snippets.

Regenerate with `scripts/gen_example_inputs.py`, which also records each cut point and
re-checks both files against the `max_windows()` guard.

## `example_paper_cohn_2025.txt` — 55,607 chars · 8 windows

> Cohn, J. (2025). Censorship of Essential Debate in Gender Medicine Research.
> *Journal of Controversial Ideas*, 5(2), 3. <https://doi.org/10.63466/jci05020003>

© 2025 the author. Open access under the
**[Creative Commons Attribution 4.0 licence (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)**,
which permits redistribution in any medium provided the original author and source are
credited — hence this file. **Unmodified except that the reference list was removed**
(the last 6 of 22 pages): reference lists carry no prose to audit and would spend most of
the 10-window budget on citation strings.

## `example_paper_wang_kosinski_2018.txt` — 39,844 chars · 6 windows

> Wang, Y., & Kosinski, M. (2018). Deep Neural Networks Are More Accurate Than Humans at
> Detecting Sexual Orientation From Facial Images. *Journal of Personality and Social
> Psychology*, 114(2), 246–257. <https://doi.org/10.1037/pspa0000098>

© 2018 American Psychological Association. **Not open access — this is a partial
quotation, reproduced for the purpose of auditing and critiquing the source text**, which
is the entire function it serves here. It is the first ~53 % of the article: the title,
abstract, introduction and prenatal-hormone-theory background, cut at the end of the
Study 3 discussion. The full 75,353-char article is 11 windows and the guard rejects it.

This is also the project's **document-level gold paper** (see `docs/PRD.md` §11). The
Achva expert annotation marks 88 spans in it, 32 of them problems; 23 of those fall inside
this excerpt, covering all four problem labels (`biased`, `outdated`,
`potentially-offensive`, `factually-incorrect`). The annotations themselves are **not**
committed — expert gold stays out of git (`data/gold/` is gitignored).

Replace this excerpt with an openly-licensed alternative if the repo is ever redistributed
as anything other than coursework.
