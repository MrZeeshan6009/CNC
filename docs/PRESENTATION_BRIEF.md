# Presentation Brief — CNC Intelligence Workbench

Written for whoever builds and delivers the pitch.
Everything here is grounded in what the repository actually does. Where something is
**verified**, the evidence is named. Where something is **not** verified, it says so — do
not upgrade those claims on stage.

---

## 0. How to use this document

| Section | Use it for |
| --- | --- |
| 1–2 | Framing the problem and the one-sentence answer |
| 3–5 | Building the architecture and "how it works" slides |
| 6 | The core narrative — this is your strongest slide |
| 7 | The mapping slide: requirement → our answer |
| 8 | The credibility slide (numbers) |
| 9 | Slide-by-slide script, ~10 slides |
| 10 | Live demo choreography |
| 11 | Q&A rehearsal |
| 12 | **Read this before you speak** — claims to avoid |

Three pitch lengths are at the end (§13). Memorise the 30-second one.

---

## 1. The problem

### 1.1 The situation in a real machine shop

Before a part can be manufactured, someone has to reconcile three documents that were
usually produced by different people, in different tools, at different times:

| Source | What it holds | What it's bad at |
| --- | --- | --- |
| **Manufacturing record** (Excel) | part number, material, revision, quantity, process notes | no geometry; rows drift, headers move, duplicates appear |
| **Engineering drawing** (PDF) | dimensions with tolerances, hole callouts, finish, notes | often image-only or inconsistently exported; text is not structured |
| **CAD model** (IGES) | exact geometry, topology, measurable volumes | carries almost no material, tolerance, or process intent |

They disagree more often than people expect — a drawing revised to 80 mm while the model
still measures 82 mm is a routine, expensive mistake. Catching it means a human reading all
three and doing arithmetic under time pressure.

### 1.2 Why "just ask an LLM" is not a solution

A language model will happily read those three files and produce a confident paragraph. In a
manufacturing context that is a liability, for three reasons:

1. **It cannot be audited.** "The part is 80 mm" is useless without the cell, page, or
   measured field that says so.
2. **It invents plausible values** when the source is missing or unreadable — exactly the
   case where a human needed to be warned.
3. **It is non-deterministic.** The same files can produce different verdicts on different
   days, which is unacceptable for a release decision.

### 1.3 The problem statement we are solving

> Given a part and any subset of {manufacturing record, drawing, CAD model}, determine
> whether the sources agree, prove it with traceable evidence, explain it in language a
> reviewer can act on — and say plainly what cannot be determined.

The last clause matters as much as the first. A tool that says "I don't know, the model is
missing" is more valuable than one that guesses.

> ⚠️ **Presenter note:** the official SPEC'26 wording lives in the challenge brief. Quote it
> from the brief if you have it on screen; use the sentence above as the paraphrase.

---

## 2. The one-paragraph answer

**CNC Intelligence Workbench** is an engineering inspection workstation that reconciles a
manufacturing record, an engineering drawing, and a CAD model for a selected part. All the
analysis that decides the verdict — Excel parsing, PDF extraction, CAD measurement with
OpenCascade, source association, and the cross-source audit — runs deterministically on the
host. A language model (DeepSeek) is then used for exactly one job: turning that verified
evidence into a readable answer with citations that are **validated against real cells,
pages, and calculated fields**. The audit decides the status; the model only explains it.

---

## 3. Architecture

```
                        ┌──────────────────────────────────────────────┐
   Excel workbook ──────▶│  Deterministic analysis (runs locally)       │
   PDF drawing ────────▶ │                                              │
   IGES model ─────────▶│  1. ingest + ZIP safety                      │
                        │  2. workbook discovery / column mapping      │
                        │  3. PDF text + OCR/vision fallback           │
                        │  4. IGES measurement (OpenCascade)           │
                        │  5. conservative source association          │
                        │  6. cross-source audit ──▶ STATUS            │
                        └───────────────────┬──────────────────────────┘
                                            │ verified evidence only
                                            ▼
                        ┌──────────────────────────────────────────────┐
                        │  DeepSeek (explanation only)                  │
                        │  answer + citations + confidence + warnings   │
                        └───────────────────┬──────────────────────────┘
                                            ▼
                        ┌──────────────────────────────────────────────┐
                        │  Citation validator                           │
                        │  drops anything that isn't a real cell/page/  │
                        │  calculated field; downgrades confidence      │
                        └───────────────────┬──────────────────────────┘
                                            ▼
                              Workbench UI (verified result + cited answer)
```

**The single most important line in this diagram:** the arrow from the audit to the status
badge does **not** pass through the language model.

### Why this shape

- **Determinism where decisions are made.** The same files always produce the same verdict.
- **The LLM is a presentation layer, not a decision layer.** Its failure degrades the
  explanation, never the verdict.
- **Everything except one HTTPS call runs locally.** No engineering file leaves the
  application; only the explanation request goes to DeepSeek.

---

## 4. How it works, stage by stage

Each stage below has a "why it's built that way" line — that is the part judges remember.

### 4.1 Ingestion and archive safety
Accepts one ZIP or individual files. Before extraction: blocks absolute paths and `..`
traversal, refuses encrypted members, caps archive at 250 MB / 250 files / 500 MB
uncompressed, and rejects suspicious compression ratios.

*Why:* an uploaded ZIP is untrusted input. A path-traversal bug in a demo is an instant
credibility loss.

### 4.2 Workbook discovery
Scans every worksheet, detects a part-number column across common headings, handles header
rows that are not row 1, and lets the operator override sheet / header row / column with a
live preview.

*Why:* real manufacturing workbooks are not tidy. Hard-coding "row 1, column A" fails on the
first real file.

### 4.3 Drawing extraction
Reads page-aware text blocks with bounding boxes. If there is too little text, it tries OCR
when Tesseract exists, otherwise renders the first pages for vision analysis.

*Why:* many drawings are scans or vector exports without text. The pipeline must degrade
instead of returning nothing.

### 4.4 CAD measurement
Transfers the IGES into OpenCascade and computes bounding dimensions, volume, surface area,
centre of mass, solid/shell/face/edge counts, and topology validity. It also detects
**cylindrical surface candidates** and generates six orthographic views plus an isometric.

*Why:* this is the only source of hard numbers. The language model never estimates geometry;
it reads measured values.

### 4.5 Source association — deliberately conservative
A drawing or model is attached to a part only when there is exactly one unambiguous
candidate, matched by filename and (for PDFs) title-block text. Ambiguity is surfaced to the
operator; unrelated files are left unassociated.

*Why:* silently attaching the wrong drawing is the worst possible failure — every downstream
check would agree confidently on the wrong part.

### 4.6 The cross-source audit — six deterministic checks
1. **Source coverage** — which of the three sources are present
2. **Part identity** — do Excel, drawing title block, and CAD filename agree
3. **Material** — Excel vs drawing (normalised, so "ALUMINIUM" = "ALUMINUM")
4. **Overall dimensions** — the three largest drawing dimensions vs CAD bounding box, within
   the drawing's own stated tolerances
5. **Hole candidates** — drawing callout (count × diameter) vs CAD cylindrical candidate groups
6. **CAD topology** — is the model a valid solid

Overall status resolves to **Conflict** → **Incomplete** → **Review** → **Consistent**, in that
precedence.

*Why the precedence:* a real disagreement outranks a missing file. And *"I couldn't check"*
is never reported as *"it's wrong."*

### 4.7 The model layer
The prompt receives only the verified record, the retrieved drawing blocks, and measured CAD
metadata. It must return JSON: `answer`, `evidence[]`, `confidence`, `warnings[]`. Response
format is pinned to JSON, temperature 0.1.

*Why:* structure is what makes validation possible. Free prose cannot be checked.

### 4.8 Citation validation
Every returned citation must match a real `Sheet!Cell` + column, a real `page N` + evidence
type, or a real calculated CAD field name. Anything unmatched is **dropped**; if nothing
survives, confidence is forced to `low` and a warning is attached.

*Why:* this is the anti-hallucination mechanism, and it is mechanical, not a prompt request.

---

## 5. The demo dataset — three parts, three lessons

Synthetic and safe to show. It is a teaching set, not a benchmark.

| Part | Status | What is inside | The lesson |
| --- | --- | --- | --- |
| **2280** | 🟢 **Consistent** | 120 × 75 × 10 mm, Aluminium 6061-T6, 4 × Ø10 holes, valid solid, all three sources agreeing | The happy path, fully cross-verified |
| **A-2281** | 🔴 **Conflict** | Drawing says **80 mm**; CAD measures **82 mm**; Stainless Steel 304 | The audit catches a real disagreement — not the LLM |
| **3300** | 🟠 **Incomplete** | Excel + drawing only; IGES intentionally absent; Aluminium 7075-T6 | Missing evidence is reported as missing, never invented |

Part **3300** is the important one to narrate: it demonstrates integrity. The tool could
easily have guessed a third dimension. It refuses.

---

## 6. The core narrative (build a slide around this)

> **"We did not build an AI that reads engineering files. We built an inspection tool that
> uses AI to explain what it has already proven."**

Three claims, in the order that makes them believable:

1. **The verdict is deterministic.** Six checks over real parsed cells, real extracted text,
   and real measured geometry. Same inputs, same answer, every time.
2. **The AI cannot overrule the checks.** Its citations are validated mechanically; invented
   ones are deleted. It cannot promote an incomplete part to consistent.
3. **Ignorance is a first-class result.** Missing sources produce *Incomplete*, ambiguous
   files require a human choice, and IGES limitations (no material, no tolerance,
   uncertain scale) are surfaced rather than papered over.

That triad — **determinism, validated citations, honest gaps** — is the whole pitch.

---

## 7. Requirement → answer mapping

Use this as the "why our design is the answer" slide.

| Requirement implied by the challenge | How this build answers it |
| --- | --- |
| Work across Excel, PDF, and CAD | One dataset, three extractors, one audit |
| Handle any subset of sources | Partial-source matrix; each subset yields a defined analysis |
| Do not invent missing data | Missing → *Incomplete*, never *Conflict*; no value inference |
| Explain results with evidence | Cell-level, page-level, field-level citations, all validated |
| Detect disagreements between sources | Identity, material, dimensions, hole callouts, topology |
| Be usable by an engineer under time pressure | Part list → 3D → verdict panel; three preset questions |
| Remain trustworthy | Deterministic precedence; LLM degradations never change the status |

---

## 8. Evidence slide — what is actually verified

| Claim | Evidence |
| --- | --- |
| Core analysis is covered by tests | **38 passed** (`pytest -q`) |
| UI handles partial and hostile datasets | **16/16** UI regression checks: PDF-only, Excel-only, IGES-only, unrelated files, refresh, two concurrent sessions |
| Graceful failure without credentials | **8/8** failure-mode checks: no key, invalid key |
| End-to-end public deployment works | Full public walkthrough (demo load, part switching, 3D, live LLM answer) with **no browser errors** |
| The AI is grounded | Live call: *high* confidence, **1 validated citation**, correct 120/75/10 answer |
| Speed | CAD measurement ≈ 2–7 s per model; LLM answer ≈ 8 s |
| Three demo outcomes reproducible | Consistent / Conflict / Incomplete asserted automatically — the Colab notebook refuses to publish a URL unless all three match |

**Say this out loud:** *"Those 38 tests and the three demo outcomes are our regression
contract. If a check breaks, the demo is not allowed to go live."*

---

## 9. Slide-by-slide script (~10 slides, 5–7 minutes)

### Slide 1 — Title
> CNC Intelligence Workbench — *verify the part, then explain it.*

### Slide 2 — The problem
Three documents, three authors, three failure modes. Show the A-2281 case as a one-liner:
**drawing 80 mm, model 82 mm.** Ask the room: *"which one would you trust?"*

### Slide 3 — Why not just prompt an LLM?
Three bullets: not auditable, invents missing values, not reproducible.
> *"In manufacturing, a confident wrong answer is worse than no answer."*

### Slide 4 — Architecture (**your diagram, §3**)
Walk the boxes left to right. Land hard on one sentence:
> *"The status badge never passes through the model."*

### Slide 5 — The six checks
List all six with one line each. Emphasise check 4 (dimensions within drawing tolerance) and
check 5 (hole callout vs cylindrical candidates).

### Slide 6 — The AI, constrained
Prompt gets verified evidence only → JSON out → validator drops invented citations →
confidence downgraded. Cover this in ~40 seconds, it is the trust slide.

### Slide 7 — Three outcomes, live or screenshots
2280 consistent · A-2281 conflict · 3300 incomplete.
For 3300 say: *"It could have guessed. It said 'no model supplied.'"*

### Slide 8 — Evidence (numbers, §8)
38 tests, 16 UI checks, 8 failure-mode checks, one public deployment.

### Slide 9 — Limits, stated by us
IGES only; IGES carries no material or tolerance; cylindrical ≠ hole; scale needs checking;
review aid, not a release certificate. Owning limits reads as competence.

### Slide 10 — Close
> *"Deterministic checks decide. The model explains. The reviewer decides what to release."*

---

## 10. Live demo choreography

Open `…/?dataset=demo` so the demo dataset is already analysed.

| # | Action | Say |
| --- | --- | --- |
| 1 | Land on part **2280** | "Three of three sources verified: 120 × 75 × 10 mm, 6061-T6, four Ø10 holes confirmed against the model." |
| 2 | Point at the **right panel** | "This is the judge-facing answer: status, dimensions, material, topology, source count." |
| 3 | Click **A-2281** | "Conflict — the drawing says 80, the CAD measures 82. The audit caught it." |
| 4 | Click **3300** | "Incomplete, not conflict. The drawing preview replaces the missing model." |
| 5 | Click a **preset question** | "Answer, confidence, and citations validated against real cells and measured fields." |
| 6 | Open **Evidence** | "Every check traces back to a cell, a page, or a calculated field." |

**Do not** open *Technical details* (raw JSON) unless asked. **Do not** scroll fast.

---

## 11. Q&A bank

**"How do you know the LLM isn't hallucinating?"**
It can't change the verdict, and its citations are validated mechanically against the real
evidence set. Unmatched citations are dropped; if none survive, confidence is forced to low
with a warning. Fabrication is detectable, not merely discouraged.

**"Why not let the LLM do the comparison? It's better at images."**
For a release decision we need reproducibility and an audit trail. The model's job is
readability; the audit's job is truth. Also, measured CAD metadata is exact — visual
estimation is strictly worse.

**"What if the wrong drawing gets attached to a part?"**
It doesn't, silently. Auto-association requires exactly one unambiguous candidate; ambiguity
requires an explicit human choice, and unrelated files stay unassociated.

**"What about material? IGES has none."**
Correct, and we say so. Material is cross-checked between the Excel record and the drawing
title block; IGES supplies geometry only.

**"Can it handle STEP or native CAD?"**
Not today — IGES only, and that's documented. The pipeline isolates format handling in one
module, so STEP is a contained addition.

**"Are those cylindrical features holes?"**
They are *candidates*. Only a drawing callout (count × diameter) promotes them to holes, and
the UI labels them accordingly.

**"What does it cost / how fast?"**
Everything except the explanation runs locally. One answer is a single API call, ~8 seconds
on the demo data.

**"Is this production ready?"**
No, and we say that on the slide: it is an engineering review aid, not a manufacturing
release or inspection certificate.

**"What's genuinely novel here?"**
The separation of concerns plus mechanical citation validation: a manufacturing inspection
tool whose verdict provably cannot be changed by a language model, and whose gaps are
reported as gaps.

**"What breaks first at scale?"**
Workbook mapping and PDF variability — real drawings have inconsistent text layers. That's
why manual mapping and OCR/vision fallbacks exist, and why the next step is a larger corpus
of real (sanitised) drawings.

---

## 12. Claims to avoid (read this twice)

| ❌ Don't say | ✅ Say instead |
| --- | --- |
| "It's 100% accurate" | "The three demo outcomes and 38 tests are our regression contract" |
| "It's hosted on Cloudflare" | "Public hosting was verified via a Cloudflare tunnel; Cloudflare Containers was evaluated and parked" |
| "It works on any CAD format" | "IGES today; STEP is a contained next step" |
| "The AI analyses the drawings" | "The AI explains evidence extracted and measured by the deterministic pipeline" |
| "It's production ready" | "It's an engineering review aid — not a release certificate" |
| "The Colab notebook is battle-tested" | "Its validation gate was executed against the shipped bundle; the notebook itself still needs one live run" |
| "It catches every error" | "It checks six specific things; anything outside those is explicitly outside scope" |

**Numbers discipline:** 38 tests, 16 UI checks, 8 failure-mode checks, 3 demo parts, ~2–7 s
CAD, ~8 s per answer. Don't invent percentages.

---

## 13. Pitch lengths

**30 seconds**
> "Manufacturing information lives in an Excel record, a drawing, and a CAD model that often
> disagree. We built a workbench that reconciles all three deterministically — six checks,
> real evidence — and then uses AI only to explain the result, with citations validated
> against actual cells and measured fields. When evidence is missing, it says so instead of
> guessing."

**60 seconds** — add after "guessing":
> "Three parts show it: one consistent, one where the drawing says 80 mm and the model
> measures 82, and one with no model at all — reported as incomplete, never as a conflict.
> The verdict is computed and auditable; the language model can make it readable but cannot
> change it."

**2 minutes** — add architecture + credibility:
> "Our pipeline parses the workbook, extracts the drawing with OCR and vision fallbacks,
> measures the IGES in OpenCascade, associates sources conservatively, and runs a six-check
> audit: coverage, identity, material, dimensions within tolerance, hole callouts, and
> topology. The model receives only that verified evidence and must return JSON; a validator
> deletes any citation that doesn't match a real cell, page, or field. 38 tests, 16 UI
> regression checks and 8 failure-mode checks back it, and the same three demo outcomes are
> asserted before we publish a URL, so a broken build can't reach a judge."

---

## Appendix — glossary for non-manufacturing judges

- **IGES** — a neutral CAD exchange format that carries geometry, not manufacturing intent.
- **OpenCascade (OCP)** — the open-source geometry kernel used to measure the model.
- **Bounding box** — the smallest box containing the part; gives overall dimensions.
- **Tolerance** — the allowed deviation, e.g. `120 ±0.10 mm`; the dimension check compares
  within the drawing's own tolerance.
- **RAG (retrieval)** — selecting the few drawing text blocks most relevant to a question
  before asking the model.
- **Deterministic** — same input, same output, every run; the opposite of sampling from a model.
