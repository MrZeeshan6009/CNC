# Technical Architecture and LLM Boundary

## 1. Purpose

CNC Part Analyzer combines three common manufacturing sources for a selected part:

- an Excel manufacturing record;
- a PDF engineering drawing; and
- an IGES CAD model.

The application extracts evidence from each supplied source, compares overlapping facts, and answers questions through DeepSeek without allowing the language model to decide the engineering status.

## 2. Architecture

```text
Files or ZIP
    |
    v
Safe ingestion and part association
    |
    +--> Excel parser ----------> cell-level facts
    +--> PDF parser + retrieval -> page/text evidence
    +--> IGES/OpenCascade ------> measured geometry + views
                                      |
                                      v
                         Deterministic cross-source audit
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
                  Status/findings UI        Evidence package
                                                   |
                                                   v
                                          DeepSeek explanation
                                                   |
                                                   v
                                         Citation validation
```

The two output paths are intentionally separate. The audit is deterministic and remains available without an API key. DeepSeek is an optional explanation layer over the extracted evidence.

## 3. Processing pipeline

### 3.1 Ingestion and association

`src/dataset_manager.py` accepts individual files or a ZIP, rejects unsafe archive paths and excessive inputs, and indexes supported Excel, PDF, and IGES files. Part-to-file association is conservative: a file is not silently attached when its identity is ambiguous. The user can resolve uncertain matches in the interface.

Every source is optional. A missing source produces an **Incomplete** result and only disables checks that require that source.

### 3.2 Excel

`src/excel_reader.py` discovers a likely data sheet and maps common header aliases to fields such as part number and material. It keeps the workbook name, sheet, cell, row, and value so results can cite the original record. Unsupported layouts can be mapped manually instead of being guessed.

### 3.3 PDF and lightweight RAG

`src/pdf_reader.py` extracts text page by page. For a question, it breaks drawing text into evidence blocks and ranks them by normalized query-term overlap. Only the top relevant blocks are sent to DeepSeek. This is lightweight retrieval-augmented generation (RAG): it does not use a vector database or embeddings because a single engineering drawing is normally short and exact identifiers and numbers matter more than semantic similarity.

If a PDF has little searchable text, up to the first three pages are rendered as images for the model. The application also keeps page-level evidence for citations.

### 3.4 IGES CAD

`src/cad_reader.py` loads IGES through OpenCascade. It calculates the bounding box, volume, surface area, center of mass, topology counts, validity, and cylindrical candidate groups. It also renders standard front, top, and isometric views.

Measured CAD metadata is authoritative for geometric values. Rendered images help explanation and presentation, but the model is not asked to estimate dimensions from pixels.

### 3.5 Deterministic audit

`src/cross_check.py` performs rule-based checks for:

- source coverage;
- part identity;
- Excel-to-drawing material agreement;
- drawing-to-CAD overall dimensions within stated tolerance;
- drawing hole callouts against CAD cylindrical candidate groups; and
- CAD topology validity.

The result vocabulary is **Consistent**, **Conflict**, **Incomplete**, or **Review**. DeepSeek cannot change these findings.

## 4. How the LLM is used

DeepSeek is used only for evidence-bound natural-language answers. `src/llm_client.py` sends:

- the selected question;
- the deterministic audit report;
- structured Excel evidence;
- retrieved PDF evidence;
- measured CAD metadata; and
- selected rendered images when useful and supported by the endpoint.

The system prompt requires JSON containing an answer, evidence list, confidence, and warnings. It explicitly treats file content as untrusted data, forbids inventing missing values, and gives priority to the deterministic audit.

After the response, the application validates every citation against known workbook cells, PDF pages or evidence blocks, and CAD fields. Unknown citations are removed and confidence is lowered. If image input is rejected, the request is retried with verified text and CAD metadata only.

Base64 may still appear inside an API request when a rendered page or CAD view is transmitted as an inline image. That is a standard transport detail and is unrelated to application distribution. The Colab notebook contains no embedded Base64 application; it clones this Git repository.

## 5. Why this works on different datasets

The implementation does not depend on the demo filenames alone:

- common Excel header aliases are detected, with manual mapping for unknown names;
- all supported files are indexed before a part is selected;
- part identifiers are normalized for punctuation and case;
- source association is explicit when multiple files could match;
- each source can be processed independently;
- PDF retrieval works on supplied drawing text rather than a fixed template; and
- IGES geometry is measured by a CAD kernel rather than inferred from a screenshot.

The test suite covers different spreadsheet layouts, PDFs with and without searchable text, optional source combinations, malicious or ambiguous ZIPs, invalid model cases, conflicts, and citation validation.

## 6. Limitations

### Data limitations

- CAD support is currently limited to IGES; STEP and native CAD formats are not supported.
- IGES often omits material, tolerance, manufacturing process, feature names, and design intent.
- A cylindrical CAD surface is only a candidate feature; geometry alone cannot reliably classify holes, bosses, counterbores, or fillets.
- Unusual IGES units or scale still require human confirmation.
- Dense GD&T frames, leader-line relationships, and poor scans may not be extracted reliably.
- Vision fallback examines only the first three image-only drawing pages.
- Novel spreadsheet structures may require manual column mapping.

### LLM limitations

- DeepSeek can misunderstand evidence or phrase an answer poorly even at low temperature.
- Citation validation confirms that a cited location exists, not that every sentence is logically correct.
- Image understanding depends on the selected model and endpoint; the application falls back to metadata when image input fails.
- Retrieval is lexical and local to one drawing, so synonyms or complex relationships can be missed.
- API availability, latency, quota, and model changes are outside the application's control.

### Operational limitations

- The Colab and Cloudflare Quick Tunnel URL is temporary and changes when the runtime restarts.
- Colab can disconnect idle sessions and reinstalls dependencies in a fresh runtime.
- Large or complex CAD models can take longer and use substantial memory.
- Uploaded files are processed in the active application session; organizations should add their own retention, access-control, and compliance policy before production use.

## 7. Safety boundary

This application is an engineering review aid. It must not automatically release a part for manufacture, replace drawing or CAD review, generate an inspection certificate, or make safety-critical acceptance decisions. A qualified engineer remains responsible for resolving conflicts and validating units, tolerances, geometry, and manufacturing intent.

## 8. Main modules

| Path | Responsibility |
| --- | --- |
| `app.py` | Application orchestration and session flow |
| `src/dataset_manager.py` | Safe ingestion and source association |
| `src/excel_reader.py` | Workbook discovery and cell evidence |
| `src/pdf_reader.py` | PDF extraction, image fallback, and RAG retrieval |
| `src/cad_reader.py` | OpenCascade measurement and CAD views |
| `src/cross_check.py` | Deterministic engineering audit |
| `src/llm_client.py` | DeepSeek request and citation validation |
| `ui/` | Streamlit interface and evidence presentation |
| `tests/` | Unit and cross-source behavior tests |
