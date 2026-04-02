# Unigest — Universal Ingest System Design

## Overview

Unigest extracts text content from arbitrary inputs — URLs, PDFs, DOCX files, XLSX spreadsheets, images, and raw blobs — and makes the extracted text available via a REST API. It is designed to handle the long tail of edge cases (paywalled sites, JS-rendered pages, captchas) through a self-improving extraction pipeline backed by a local LLM.

The system serves as the content ingestion layer for a "subscribe to anything" social media replacement, where users subscribe to blogs, journals, news searches, podcasts, etc.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Caller (subscriber app, CLI, etc.)                  │
│  POST /jobs         → submit extraction job          │
│  GET  /jobs/{id}    → poll status + result           │
│  Webhook callback on completion                      │
└──────────────────┬───────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────┐
│  Unigest Server                                      │
│  (Cloud Run in prod / localhost in dev)               │
│  ┌─────────────────────────────────────────────┐     │
│  │  REST API (FastAPI)                         │     │
│  │  - Job submission & status                  │     │
│  │  - Cache lookup (content-hash / URL)        │     │
│  │  - Webhook dispatch                         │     │
│  │  - Human-in-the-loop stub endpoints         │     │
│  │  - Extractor registry (CRUD)                │     │
│  └─────────────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────┐     │
│  │  Postgres (Neon.tech in prod / local in dev)│     │
│  │  - Jobs table (queue)                       │     │
│  │  - Results table (cache)                    │     │
│  │  - Extractors table (learned strategies)    │     │
│  │  - Extraction logs (for self-improvement)   │     │
│  │  - HITL requests table                      │     │
│  └─────────────────────────────────────────────┘     │
└──────────────────┬───────────────────────────────────┘
                   │ polls for jobs / posts results
┌──────────────────▼───────────────────────────────────┐
│  Unigest Worker (runs locally on Mac)                │
│  ┌─────────────────────────────────────────────┐     │
│  │  Job Runner                                 │     │
│  │  - Polls server for pending jobs            │     │
│  │  - Routes to appropriate extraction stage   │     │
│  │  - Posts results back to server             │     │
│  └──────────┬──────────────────────────────────┘     │
│  ┌──────────▼──────────────────────────────────┐     │
│  │  Extraction Pipeline (waterfall)            │     │
│  │  1. Cache hit → done                        │     │
│  │  2. Domain-specific extractor (if learned)  │     │
│  │  3. Generic extractor (trafilatura, etc.)   │     │
│  │  4. Headless browser + generic extraction   │     │
│  │  5. LLM-assisted extraction                 │     │
│  │  6. Human-in-the-loop request               │     │
│  └──────────┬──────────────────────────────────┘     │
│  ┌──────────▼──────────────────────────────────┐     │
│  │  Quality Checker                            │     │
│  │  - Structural coherence (sentences, paras)  │     │
│  │  - Minimum length / boilerplate ratio       │     │
│  │  - Encoding sanity                          │     │
│  └──────────┬──────────────────────────────────┘     │
│  ┌──────────▼──────────────────────────────────┐     │
│  │  Self-Improvement Engine                    │     │
│  │  - On failure: diagnose via LLM             │     │
│  │  - Generate candidate extractor             │     │
│  │  - Sandbox-test it                          │     │
│  │  - Promote after N successes                │     │
│  └──────────┬──────────────────────────────────┘     │
│             │ LLM calls                              │
│  ┌──────────▼──────────────────────────────────┐     │
│  │  Gemma 4 (local via Ollama)                 │     │
│  └─────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────┘
```

## Data Models

### Jobs

```sql
CREATE TABLE jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status        TEXT NOT NULL DEFAULT 'pending',
        -- pending | processing | completed | failed | needs_hitl
    input_type    TEXT NOT NULL,
        -- url | blob | base64
    input_value   TEXT NOT NULL,
        -- the URL, or for blobs/base64: a reference to stored content
    content_hash  TEXT,
        -- SHA-256 of the input content (for dedup/caching)
    mime_type     TEXT,
        -- detected or provided MIME type (e.g., text/html, application/pdf)
    webhook_url   TEXT,
        -- optional callback URL
    result_id     UUID REFERENCES results(id),
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ
);

CREATE INDEX idx_jobs_status ON jobs(status, created_at);
CREATE INDEX idx_jobs_content_hash ON jobs(content_hash);
```

### Results

```sql
CREATE TABLE results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash    TEXT NOT NULL,
        -- SHA-256 of the input (for cache lookups)
    extracted_text  TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
        -- title, author, date, word_count, language, source_url, etc.
    quality_score   REAL,
        -- 0.0 to 1.0, from automated quality check
    extraction_strategy TEXT NOT NULL,
        -- which pipeline stage produced this result
    extractor_id    UUID REFERENCES extractors(id),
        -- if a learned extractor was used
    flagged         BOOLEAN NOT NULL DEFAULT false,
        -- user-flagged as bad quality
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_results_content_hash ON results(content_hash);
```

### Extractors (Learned Strategies)

```sql
CREATE TABLE extractors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          TEXT NOT NULL,
        -- e.g., "nytimes.com", or "*" for generic improvements
    name            TEXT NOT NULL,
        -- human-readable description
    code            TEXT NOT NULL,
        -- Python source code of the extractor function
    config          JSONB NOT NULL DEFAULT '{}',
        -- headers, cookies, selectors, delays, etc.
    status          TEXT NOT NULL DEFAULT 'candidate',
        -- candidate | trusted | disabled
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at     TIMESTAMPTZ,
        -- when it moved from candidate to trusted
    parent_id       UUID REFERENCES extractors(id)
        -- if this was derived from improving another extractor
);

CREATE INDEX idx_extractors_domain ON extractors(domain, status);
```

### Extraction Logs (for self-improvement analysis)

```sql
CREATE TABLE extraction_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id),
    stage           TEXT NOT NULL,
        -- cache | domain_extractor | generic | headless | llm_assisted | hitl
    extractor_id    UUID REFERENCES extractors(id),
    success         BOOLEAN NOT NULL,
    quality_score   REAL,
    duration_ms     INTEGER,
    error_type      TEXT,
        -- timeout | http_403 | captcha | empty_content | low_quality | etc.
    error_detail    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_extraction_logs_job ON extraction_logs(job_id);
CREATE INDEX idx_extraction_logs_error ON extraction_logs(error_type, created_at);
```

### Human-in-the-Loop Requests

```sql
CREATE TABLE hitl_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id),
    request_type    TEXT NOT NULL,
        -- captcha | authenticated_page | manual_extraction
    instructions    TEXT NOT NULL,
        -- what the user needs to do
    target_url      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
        -- pending | claimed | completed | expired
    response_data   TEXT,
        -- the HTML, captcha solution, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_hitl_status ON hitl_requests(status, created_at);
```

## API Endpoints

### Job Management

```
POST /jobs
    Request:
        {
            "input_type": "url" | "blob" | "base64",
            "input_value": "https://example.com/article" | "<base64 string>",
            "mime_type": "application/pdf",        // optional, auto-detected if omitted
            "webhook_url": "https://callback.example.com/done",  // optional
            "force_refresh": false                 // optional, bypass cache
        }
    Response: 201
        {
            "job_id": "uuid",
            "status": "pending",
            "cached": false
        }
    Notes:
        - If a cached result exists for the content hash and force_refresh is false,
          returns immediately with status "completed" and cached: true.

GET /jobs/{id}
    Response: 200
        {
            "job_id": "uuid",
            "status": "processing",
            "input_type": "url",
            "created_at": "2026-04-02T...",
            "started_at": "2026-04-02T...",
            "completed_at": null,
            "result": null,             // populated when status=completed
            "error": null               // populated when status=failed
        }

GET /jobs/{id}/result
    Response: 200
        {
            "extracted_text": "The full extracted text...",
            "metadata": {
                "title": "Article Title",
                "author": "Author Name",
                "word_count": 1523,
                "source_url": "https://..."
            },
            "quality_score": 0.87,
            "extraction_strategy": "domain_extractor"
        }
    Response: 404 if job not found or not yet completed.

POST /jobs/{id}/flag
    Request:
        {
            "reason": "missing_content" | "wrong_content" | "garbled" | "other",
            "detail": "The article was cut off after the third paragraph"
        }
    Response: 200
    Notes:
        - Marks the result as flagged.
        - Triggers a re-extraction attempt using a more aggressive strategy.
```

### Human-in-the-Loop (Stub)

```
GET /hitl/pending
    Response: 200
        [
            {
                "id": "uuid",
                "job_id": "uuid",
                "request_type": "captcha",
                "instructions": "Solve the captcha at this URL",
                "target_url": "https://...",
                "expires_at": "2026-04-02T..."
            }
        ]
    Notes:
        - Browser extension polls this endpoint.

POST /hitl/{id}/complete
    Request:
        {
            "response_data": "<html>...</html>"   // or captcha solution
        }
    Response: 200
    Notes:
        - Marks request as completed, resumes the blocked job.
```

### Worker Communication

```
GET /worker/jobs?limit=5
    Response: 200
        [{"job_id": "uuid", "input_type": "url", "input_value": "...", ...}]
    Notes:
        - Returns up to N pending jobs, atomically marking them as "processing".
        - Worker polls this endpoint.

POST /worker/jobs/{id}/result
    Request:
        {
            "extracted_text": "...",
            "metadata": {...},
            "quality_score": 0.87,
            "extraction_strategy": "generic",
            "logs": [
                {"stage": "generic", "success": true, "duration_ms": 230, ...}
            ]
        }
    Response: 200

POST /worker/jobs/{id}/fail
    Request:
        {
            "error_type": "captcha",
            "error_detail": "Cloudflare Turnstile challenge detected",
            "logs": [...]
        }
    Response: 200

POST /worker/jobs/{id}/hitl
    Request:
        {
            "request_type": "captcha",
            "instructions": "...",
            "target_url": "..."
        }
    Response: 200
    Notes:
        - Creates a HITL request and moves job to needs_hitl status.
```

### Admin / Extractors

```
GET /extractors?domain=nytimes.com
    Response: list of extractors for domain

GET /extractors/{id}
    Response: extractor details including code

POST /extractors/{id}/disable
    Response: 200
```

## Extraction Pipeline Detail

The worker processes each job through a waterfall of stages. Each stage either succeeds (producing extracted text) or fails (falling through to the next stage). Every attempt is logged.

### Stage 1: Cache Lookup

Check the server for an existing result matching the content hash (for blobs/base64) or the URL (for URL inputs). If found and not flagged, return it immediately.

### Stage 2: Domain-Specific Extractor

For URL inputs, check if a trusted extractor exists for this domain. If so, run it. Domain extractors are Python functions with a standard signature:

```python
async def extract(url: str, http_client: HttpClient, browser: Browser | None) -> ExtractionResult:
    """
    Returns ExtractionResult(text=str, metadata=dict) or raises ExtractionError.
    """
```

These are loaded from the `extractors` table and executed in a subprocess sandbox with restricted filesystem access and a timeout.

### Stage 3: Generic Extraction

Based on the detected content type:

| Content Type | Library | Approach |
|---|---|---|
| HTML (from URL) | `trafilatura` | Article extraction with boilerplate removal |
| PDF | `pymupdf` | Direct text extraction; fall back to OCR if text layer is empty |
| DOCX | `python-docx` | Iterate paragraphs + tables |
| XLSX | `openpyxl` | Read all cells across sheets, format as structured text |
| Image | `pytesseract` | OCR with preprocessing (deskew, binarize via Pillow) |
| Plain text | — | Pass through with encoding detection |

For URLs: fetch with `curl_cffi` (which mimics browser TLS fingerprints) and appropriate headers before passing to trafilatura.

### Stage 4: Headless Browser + Generic Extraction

If generic extraction fails or returns low-quality results (e.g., JS-rendered content):

1. Launch Playwright (Chromium) with `playwright-stealth` patches
2. Navigate to URL, wait for content to render
3. Extract the page HTML
4. Re-run trafilatura on the rendered HTML

### Stage 5: LLM-Assisted Extraction

If the headless browser approach also fails or returns low quality:

1. Capture the page HTML (or screenshot for visual analysis)
2. Send to Gemma 4 with a prompt like:
   ```
   The following HTML is from {url}. Extract the main text content,
   removing navigation, ads, footers, and other boilerplate.
   Return only the article/document text.
   ```
3. Validate the LLM output against quality checks

This is the most expensive stage in compute time but handles edge cases that rule-based extraction can't.

### Stage 6: Human-in-the-Loop

If all automated approaches fail (e.g., captcha, login wall):

1. Create a HITL request via the server API
2. Move job to `needs_hitl` status
3. Wait for the browser extension to provide the page content
4. When response arrives, run the content through stages 2-5

## Quality Checking

Every extraction result passes through quality checks before being accepted. The checker produces a score from 0.0 to 1.0.

### Checks

1. **Structural coherence** (weight: 40%)
   - Ratio of text that forms complete sentences (contains subject/verb, ends with punctuation)
   - Average sentence length (flag if <3 words or >100 words)
   - Paragraph structure (at least some newline-separated blocks)

2. **Boilerplate ratio** (weight: 25%)
   - Compare extracted text against known boilerplate patterns (cookie notices, nav menus, "subscribe to newsletter")
   - Flag if >40% of text matches boilerplate patterns

3. **Minimum content length** (weight: 20%)
   - For URLs: expect at least ~100 words (configurable per content type)
   - For PDFs/DOCX: expect text proportional to page/file size

4. **Encoding sanity** (weight: 15%)
   - No replacement characters (U+FFFD)
   - No runs of non-printable characters
   - Valid UTF-8

### Thresholds

- Score >= 0.6: **Accept** the result
- Score 0.3-0.6: **Accept with warning**, log for potential improvement
- Score < 0.3: **Reject**, fall through to next pipeline stage

## Self-Improvement Engine

### On Extraction Failure

When all pipeline stages fail, or produce results below the quality threshold:

1. **Diagnose**: Send the LLM a summary of what was tried and what failed:
   ```
   URL: https://example.com/article
   Attempts:
   - curl_cffi + trafilatura: HTTP 403, Cloudflare challenge detected
   - Playwright + trafilatura: Page loaded but extracted text was only 12 words
   - LLM extraction: Returned "Access denied" text only

   The page likely contains an article about [topic].
   Diagnose why extraction failed and propose a fix.
   ```

2. **Generate**: The LLM writes a candidate extractor function targeting the failure mode. The function must conform to the standard extractor signature.

3. **Test**: Run the candidate extractor against the original input in a sandboxed subprocess:
   - No filesystem access outside `/tmp`
   - No network access except to the target URL
   - 30-second timeout
   - Memory limit (512MB)

4. **Validate**: Run quality checks on the output. If the score is >= 0.6, save the extractor as a `candidate` in the database.

5. **Promote**: Track the extractor's success/failure rate across subsequent jobs for the same domain. After 3 successes with 0 failures, promote to `trusted`.

### Periodic Review (Generalization)

On a schedule (e.g., daily), the system reviews extraction logs to find patterns:

1. Query for common failure modes across domains:
   ```sql
   SELECT error_type, COUNT(*) as cnt
   FROM extraction_logs
   WHERE success = false
     AND created_at > now() - interval '7 days'
   GROUP BY error_type
   ORDER BY cnt DESC;
   ```

2. For recurring patterns (e.g., "Cloudflare challenge on 15 different domains this week"), ask the LLM to propose a generic improvement to the pipeline — not a domain-specific extractor but a change to the generic extraction stages.

3. Generic improvements are saved with `domain = '*'` and go through the same candidate/trusted promotion cycle, but require a higher threshold (5 successes across 3+ domains).

### Safety Rails

- **Rate limit**: Max 10 improvement cycles per hour (prevents runaway LLM loops)
- **Code review log**: All generated extractor code is stored with full provenance (which failure triggered it, the LLM conversation that produced it)
- **Kill switch**: Admin endpoint to disable all candidate extractors instantly
- **No persistence**: Generated code runs in subprocesses with no ability to write to the worker's filesystem (except `/tmp`, which is cleared between runs)
- **No outbound network beyond target**: Sandbox blocks network access to anything other than the job's target URL

## Project Structure

```
unigest/
├── pyproject.toml
├── DESIGN.md
├── README.md
│
├── server/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, lifespan, CORS
│   ├── config.py               # Settings (DB URL, dev/prod mode, etc.)
│   ├── models.py               # SQLAlchemy / Pydantic models
│   ├── db.py                   # Database connection, migrations
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── jobs.py             # POST /jobs, GET /jobs/{id}, etc.
│   │   ├── hitl.py             # HITL stub endpoints
│   │   ├── worker.py           # Worker polling & result submission
│   │   └── extractors.py       # Extractor registry admin
│   └── webhook.py              # Async webhook dispatcher
│
├── worker/
│   ├── __init__.py
│   ├── main.py                 # Worker entry point, job polling loop
│   ├── config.py               # Worker settings (LLM endpoint, etc.)
│   ├── pipeline.py             # Orchestrates the extraction waterfall
│   ├── quality.py              # Quality checking logic
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── cache.py            # Stage 1: cache lookup
│   │   ├── domain_extractor.py # Stage 2: run learned extractors
│   │   ├── generic.py          # Stage 3: trafilatura, pymupdf, etc.
│   │   ├── headless.py         # Stage 4: Playwright-based extraction
│   │   ├── llm_assisted.py     # Stage 5: LLM extraction
│   │   └── hitl.py             # Stage 6: human-in-the-loop
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── html.py             # trafilatura wrapper
│   │   ├── pdf.py              # pymupdf + OCR fallback
│   │   ├── docx.py             # python-docx wrapper
│   │   ├── xlsx.py             # openpyxl wrapper
│   │   └── image.py            # pytesseract wrapper
│   ├── sandbox.py              # Subprocess sandbox for generated code
│   └── improvement/
│       ├── __init__.py
│       ├── engine.py           # Self-improvement loop orchestration
│       ├── diagnosis.py        # Failure analysis via LLM
│       ├── codegen.py          # Extractor generation via LLM
│       └── review.py           # Periodic generalization review
│
├── shared/
│   ├── __init__.py
│   ├── types.py                # Shared types (ExtractionResult, etc.)
│   └── hashing.py              # Content hashing utilities
│
├── migrations/
│   └── ...                     # Alembic migrations
│
├── tests/
│   ├── server/
│   ├── worker/
│   └── integration/
│
├── Dockerfile.server            # For Cloud Run deployment
├── docker-compose.yml           # Dev mode: server + postgres + worker
└── scripts/
    ├── dev.sh                  # Start dev environment
    └── deploy.sh               # Deploy server to Cloud Run
```

## Dependencies

```
# Server
fastapi
uvicorn
sqlalchemy[asyncio]
asyncpg              # async Postgres driver
pydantic
httpx                # for webhook dispatch
alembic              # migrations

# Worker - Extraction
trafilatura          # HTML article extraction
pymupdf              # PDF text extraction
pdfplumber           # PDF table extraction
python-docx          # DOCX extraction
openpyxl             # XLSX extraction
pytesseract          # OCR
Pillow               # Image preprocessing
playwright           # Headless browser
playwright-stealth   # Anti-detection
curl_cffi            # TLS fingerprint mimicry
fake-useragent       # User-agent rotation

# Worker - LLM
ollama               # Gemma 4 client (or httpx to Ollama REST API)

# Shared
python-magic         # MIME type detection
```

## Configuration

### Environment Variables

```bash
# Server
DATABASE_URL=postgresql+asyncpg://user:pass@host/unigest
DEV_MODE=true                    # true = run everything locally
WEBHOOK_TIMEOUT_SECONDS=10

# Worker
SERVER_URL=http://localhost:8000  # or https://unigest-xyz.run.app
LLM_ENDPOINT=http://localhost:11434  # Ollama
LLM_MODEL=gemma4
POLL_INTERVAL_SECONDS=5
MAX_CONCURRENT_JOBS=1            # single ephemeral worker
SANDBOX_TIMEOUT_SECONDS=30
SANDBOX_MEMORY_MB=512
IMPROVEMENT_RATE_LIMIT=10        # max improvement cycles per hour
```

### Dev Mode

When `DEV_MODE=true`:
- Server runs on `localhost:8000`
- Uses local Postgres (via docker-compose or a local install)
- Worker connects to `localhost:8000`
- Ollama runs locally at `localhost:11434`
- Everything starts with `docker-compose up` or `scripts/dev.sh`

### Prod Mode

- Server deployed to Google Cloud Run
- Database on Neon.tech
- Worker runs on local Mac, connects to Cloud Run server URL
- Ollama runs on local Mac

## Deployment

### Server (Cloud Run)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY server/ server/
COPY shared/ shared/
COPY pyproject.toml .
RUN pip install .[server]
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Cloud Run config:
- Min instances: 0 (scale to zero when idle)
- Max instances: 2 (modest scale for 1k req/day)
- Memory: 512MB (server is lightweight)
- CPU: 1
- Concurrency: 100

### Worker (Local Mac)

Run directly or in a Docker container for isolation:
```bash
# Direct (dev)
python -m worker.main

# Docker (prod-like isolation)
docker run --rm \
  -e SERVER_URL=https://unigest-xyz.run.app \
  -e LLM_ENDPOINT=http://host.docker.internal:11434 \
  unigest-worker
```

## Webhook Contract

When a job completes (or fails), if `webhook_url` was provided:

```
POST {webhook_url}
Content-Type: application/json

{
    "job_id": "uuid",
    "status": "completed" | "failed",
    "result": {
        "extracted_text": "...",
        "metadata": {...},
        "quality_score": 0.87
    },
    "error": null | {
        "type": "captcha",
        "detail": "..."
    }
}
```

Webhook delivery:
- Timeout: 10 seconds
- Retries: 3 with exponential backoff (1s, 5s, 25s)
- No retry on 2xx response

## Caching Strategy

- **Cache key**: SHA-256 of the input content (for blobs/base64) or normalized URL (for URL inputs)
- **Cache hit**: Return the existing result immediately, set `cached: true` on the job response
- **Cache invalidation**: `force_refresh: true` on job submission bypasses cache and creates a new extraction
- **Flagged results**: When a user flags a result, it's still cached but marked — subsequent requests will see it but may choose to re-extract
- **No TTL for now**: Content doesn't expire from cache. We can add TTL later if needed for frequently-updating sources.

## Security Considerations

### Worker Sandbox (for generated extractors)

Generated extractor code runs in a subprocess with:
- **No filesystem access** outside `/tmp` (cleared after each run)
- **Network restricted** to the target URL only (via a subprocess-level proxy or network namespace)
- **Timeout**: 30 seconds hard kill
- **Memory limit**: 512MB
- **No access to worker config, credentials, or LLM endpoint**

### Server

- **Input validation**: Reject absurdly large inputs (>100MB blobs, >10k char URLs)
- **Rate limiting**: Per-client rate limits on job submission
- **Webhook SSRF prevention**: Validate webhook URLs against a blocklist (no localhost, no internal IPs)
- **SQL injection**: Handled by SQLAlchemy parameterized queries

### Worker ↔ Server Authentication

- **Dev mode**: No auth
- **Prod mode**: Shared secret in `Authorization: Bearer <token>` header. The worker includes this on all server API calls. Simple but sufficient for a single trusted worker.

## Future Considerations (Not in v1)

- **Browser extension** for HITL (APIs are stubbed, implementation deferred)
- **Multiple workers** / worker pool scaling
- **Image/icon extraction** from documents
- **Streaming results** (partial text as extraction progresses)
- **Cloud LLM fallback** if Gemma 4 can't handle improvement tasks
- **Content TTL / re-extraction scheduling** for sources that update frequently
- **User accounts / multi-tenancy** on the server
