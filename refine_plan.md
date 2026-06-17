# Email Intelligence RAG System — Refined Production Plan

## Project Goal

Build a production-grade Email Intelligence Assistant for **SMB Freight FZE** aviation operations capable of:

* Understanding aviation-related operational emails (slot requests, landing permissions, flight schedules, cargo operations)
* Searching across historical communications with metadata-first retrieval
* Explaining decisions buried inside email threads
* Summarizing request histories and lifecycle tracking
* Retrieving information using hybrid RAG (metadata filters + dense + sparse vectors)
* Producing grounded answers with email citations
* Supporting monitoring, evaluation, versioning, and observability

---

## Design Philosophy

> **Metadata quality is more important than embedding quality.**

This system is NOT a generic document chatbot. The source data is **operational email communication** between aviation stakeholders — AOCC (Airport Operations Control Centre), airlines (SalamAir/OV), ground handlers (Omega Air), and freight operators (SMB Freight).

Email types include:
* Slot requests & approvals
* Landing permission requests & approvals
* Flight schedule updates (with tabular data)
* YA (Overflight/Landing) permit submissions
* Cargo/handling service requests
* Operational confirmations & acknowledgments
* Invoice & payment communications
* DGCA/regulatory compliance notices

Therefore: **Most user queries should route through metadata filters first, falling back to vector search only when semantic understanding is required.**

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA PIPELINE                            │
│                                                                 │
│  Raw Emails (JSONL)                                             │
│       ↓                                                         │
│  Phase 0: Scraping  ──→  data/raw/emails.jsonl    ✅ DONE       │
│       ↓                                                         │
│  Phase 1: Cleaning  ──→  data/cleaned/emails.jsonl              │
│       ↓                                                         │
│  Phase 2: Metadata Extraction  ──→  enriched records            │
│       ↓                                                         │
│  Phase 3: Entity Extraction  ──→  structured entities           │
│       ↓                                                         │
│  Phase 4: Versioning  ──→  data/versions/                       │
│       ↓                                                         │
│  Phase 5: Structural Chunking  ──→  data/processed/chunks.jsonl │
│       ↓                                                         │
│  Phase 6: Embedding Pipeline  ──→  dense + sparse vectors       │
│       ↓                                                         │
│  Phase 7: Qdrant Ingestion  ──→  knowledge_v1 collection        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       QUERY PIPELINE                            │
│                                                                 │
│  User Query                                                     │
│       ↓                                                         │
│  Phase 8:  Query Understanding  ──→  intent + parsed filters    │
│       ↓                                                         │
│  Phase 9:  Retrieval Layer  ──→  candidate emails               │
│       ↓                                                         │
│  Phase 10: Re-ranking  ──→  top-K relevant emails               │
│       ↓                                                         │
│  Phase 11: Context Construction  ──→  assembled context         │
│       ↓                                                         │
│  Phase 12: Prompt Engineering  ──→  final prompt                │
│       ↓                                                         │
│  Phase 13: LLM Layer  ──→  generated answer                     │
│       ↓                                                         │
│  Phase 14: Guardrails  ──→  validated safe response             │
│       ↓                                                         │
│  Response with citations                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE                               │
│                                                                 │
│  Phase 15: API Layer (FastAPI service.py)                       │
│  Phase 16: Observability (logging, metrics, tracing)            │
│  Phase 17: Evaluation (retrieval + RAG quality)                 │
│  Phase 18: Config & Environment Management                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Refined Folder Structure

```
rag_pipeline/
│
├── config/
│   ├── __init__.py
│   └── settings.py              # [NEW] Centralized config (env vars, model names, Qdrant URL)
│
├── scraping/
│   ├── __init__.py              # [NEW]
│   └── scraper.py               # ✅ EXISTS — IMAP email scraper
│
├── cleaning/
│   ├── __init__.py              # [NEW]
│   ├── cleaning.py              # Main cleaning pipeline
│   ├── email_normalizer.py      # Email-specific normalization
│   └── learning.md
│
├── metadata/
│   ├── __init__.py              # [NEW]
│   ├── extractors.py            # Metadata extraction (request_id, status, dates)
│   ├── classifier.py            # Email type classification
│   ├── entities.py              # [RENAME from entites.py] Entity extraction
│   └── learning.md
│
├── versioning/
│   ├── __init__.py              # [NEW]
│   ├── document_versioning.py   # Document version tracking
│   ├── embedding_versioning.py  # Embedding version tracking
│   └── learning.md              # [RENAME from leaning.md]
│
├── ingestion/
│   ├── __init__.py              # [NEW]
│   ├── chunker.py               # Structural chunking (1 email = 1 chunk)
│   ├── embed.py                 # Dense + sparse embedding generation
│   ├── qdrant.py                # Qdrant collection management & upsert
│   └── learning.md              # [RENAME from learning (no ext)]
│
├── retrieval/
│   ├── __init__.py              # [NEW]
│   ├── hybrid.py                # Hybrid search (dense + sparse + RRF fusion)
│   ├── reranker.py              # Cross-encoder re-ranking
│   ├── filters.py               # Metadata filter construction
│   └── learning.md
│
├── llm/
│   ├── __init__.py              # [NEW]
│   └── client.py                # LLM gateway (Gemini / OpenAI)
│
├── prompting/
│   ├── __init__.py              # [NEW]
│   └── builder.py               # Prompt template construction
│
├── guardrails/
│   ├── __init__.py              # [NEW]
│   ├── pii.py                   # PII detection & masking
│   └── validation.py            # Input/output validation
│
├── observability/
│   ├── __init__.py              # [NEW]
│   ├── logging.py               # Structured logging setup
│   ├── metrics.py               # Latency & usage metrics
│   ├── tracing.py               # Request tracing
│   └── learning.md
│
├── evaluation/
│   ├── __init__.py              # [NEW]
│   ├── rag_eval.py              # End-to-end RAG evaluation
│   ├── retrieval_eval.py        # Retrieval-specific evaluation
│   └── learning.md
│
├── data/
│   ├── raw/
│   │   └── emails.jsonl         # ✅ EXISTS — 699 scraped emails (~900KB)
│   ├── cleaned/
│   ├── processed/
│   ├── evaluation/
│   └── versions/
│
├── tests/                       # [NEW] Test directory
│   ├── test_cleaning.py
│   ├── test_metadata.py
│   ├── test_chunking.py
│   ├── test_retrieval.py
│   └── test_guardrails.py
│
├── .env.example                 # [NEW] Environment variable template
├── .gitignore                   # Needs content
├── requirements.txt             # Needs content
├── dvc.yaml                     # [NEW] DVC pipeline stages definition
├── params.yaml                  # [NEW] Configuration parameters for DVC stages
├── architecture.md              # System architecture diagram
├── plan.md                      # Original plan (preserved)
├── refine_plan.md               # This file
└── service.py                   # FastAPI entrypoint
```

---

## Data Schema (Derived from Actual Email Data)

### Raw Email Schema (from scraper.py → emails.jsonl)

```json
{
  "id":        "<message-id>",
  "subject":   "RE: Slot Request for OV Freighter dated 09-05-2024.",
  "body":      "Dear Sir/Madam, The slot timings for...",
  "from":      ["aocc.planning@adani.com"],
  "to":        ["slots@smb-freight.com", "Slot.Management@adani.com"],
  "date":      "2024-05-06T13:33:12+00:00",
  "thread_id": "<root-message-id>",
  "reply_to":  "<parent-message-id>"
}
```

### Cleaned + Enriched Email Schema (target output after Phases 1–3)

```json
{
  "email_id":       "<message-id>",
  "thread_id":      "<root-message-id>",
  "reply_to":       "<parent-message-id>",
  "subject":        "RE: Slot Request for OV Freighter dated 09-05-2024.",
  "body_clean":     "The slot timings for the proposed flight are noted...",
  "from":           ["aocc.planning@adani.com"],
  "to":             ["slots@smb-freight.com"],
  "date":           "2024-05-06T13:33:12+00:00",

  "email_type":     "slot_approval",
  "status":         "conditional_approval",
  "request_id":     null,
  "direction":      "inbound",

  "entities": {
    "companies":        ["Mumbai International Airport Ltd", "Adani Airports"],
    "persons":          ["Mohak Patwardhan"],
    "airports":         ["VABB", "BOM"],
    "aircraft_reg":     [],
    "flight_numbers":   [],
    "notam_refs":       ["A1547/23", "A0239/24"],
    "conditions":       ["SERVICEABLE TOW-BAR on board OR with ground handling agency"]
  },

  "document_version":  "v1",
  "embedding_version": "emb_v1",
  "processed_at":      "2025-06-17T10:00:00Z"
}
```

---

## Phase-by-Phase Implementation

---

### Phase 0 — Scraping ✅ DONE

**Status:** Complete

**File:** `scraping/scraper.py` (222 lines)

**What it does:**
- IMAP SSL connection with retry logic (3 attempts, 5s delay)
- `BODY.PEEK[]` fetch (doesn't mark as read)
- Reply-chain stripping via regex
- HTML → plain text via BeautifulSoup
- Thread resolution via `In-Reply-To` / `References` headers
- Progress tracking for resumable runs
- Output: `data/raw/emails.jsonl` (699 records, ~900KB)

**No changes needed.**

---

### Phase 1 — Data Cleaning

**Goal:** Convert noisy raw emails into clean, searchable content.

**File:** `cleaning/cleaning.py`

**What to remove:**
| Pattern | Example from actual data |
|---|---|
| Greetings | `"Dear AOCC Team,"`, `"Dear Sir/Madam,"`, `"Dear Ibrahim,"` |
| Signatures | `"Regards, Yasar Saquib Shaikh, Operations Executive, SMB-F, (+91-7304677451)"` |
| Corporate signatures | `"Airport Operations Control Centre, Mumbai International Airport Pvt Ltd..."` |
| Email footers | `"Get Outlook for iOS"`, `"Sent from my iPhone"` |
| CID image references | `[cid:c01e7193-1bc6-484c-bc9f-c537346061e6]` |
| Marketing taglines | `"Asia's Youngest Aircraft Fleet 2022 – ch-aviation"` |
| IONOS system emails | `"Welcome to Mail Basic"`, `"Daily report mailbox..."` |
| Confidentiality disclaimers | Full confidentiality notice blocks |
| Excessive whitespace | `\r\n     \r\n  \n\n\n\r\n` patterns |
| Social media link blocks | LinkedIn, Twitter, Facebook, Instagram, YouTube blocks |

**What to keep:**
| Content | Example |
|---|---|
| Operational decisions | `"The slot timings for the proposed flight are noted and shall be considered favourable"` |
| Conditions | `"This slot is approved with a precondition of having serviceable TOW-BAR on board"` |
| NOTAM references | `"NOTAM NO: A0239/24 (Curfew Period...)"` |
| Flight schedules | Tabular flight data (OV 3897, RKT→BOM, etc.) |
| Status updates | `"YA copy received"`, `"Slot is confirmed"` |
| Action items | `"Request you to forward us the DGCA approval"` |

**File:** `cleaning/email_normalizer.py`

**Responsibilities:**
- Normalize sender/recipient email addresses (lowercase, trim)
- Standardize date formats to ISO 8601
- Deduplicate emails by `id` field
- Filter out system/spam emails (IONOS notifications, spam reports)
- Handle encoding issues in body text

**Implementation approach:**
```python
class EmailCleaner:
    def __init__(self):
        self.greeting_patterns: list[re.Pattern]   # regex list
        self.signature_patterns: list[re.Pattern]
        self.footer_patterns: list[re.Pattern]
        self.cid_pattern: re.Pattern
        self.whitespace_pattern: re.Pattern

    def clean(self, raw_email: dict) -> dict:
        """Full cleaning pipeline for a single email."""

    def remove_greetings(self, text: str) -> str: ...
    def remove_signatures(self, text: str) -> str: ...
    def remove_disclaimers(self, text: str) -> str: ...
    def remove_cid_refs(self, text: str) -> str: ...
    def normalize_whitespace(self, text: str) -> str: ...
    def is_system_email(self, email: dict) -> bool: ...

def clean_all(input_path: Path, output_path: Path) -> CleaningReport:
    """Process all emails and write cleaned output."""
```

**Output:** `data/cleaned/emails.jsonl`

**Learning.md topics:**
- Why cleaning matters for RAG quality
- Signal vs noise in email bodies
- Regex-based vs ML-based cleaning tradeoffs
- Impact of noise on embedding quality and retrieval precision

---

### Phase 2 — Metadata Extraction

**Goal:** Convert hidden structure into searchable, filterable metadata.

**File:** `metadata/extractors.py`

**Fields to extract:**

| Field | Method | Example |
|---|---|---|
| `request_id` | Regex: `[A-Z]{2,4}RQ-\d{2}-\d{2}-\d{4}-\d{4,5}` | `LPRQ-08-03-2025-48431` |
| `email_type` | LLM classification (Phase 2b) | `slot_approval`, `landing_permission` |
| `status` | Keyword matching + LLM | `approved`, `pending`, `conditional` |
| `direction` | From/to address matching | `inbound` (to SMB) / `outbound` (from SMB) |
| `airports` | ICAO/IATA code regex + lookup | `VABB`, `BOM`, `OMSJ`, `SHJ` |
| `flight_numbers` | Regex: `[A-Z]{2}\d{3,4}` | `OV3897`, `JAG1316` |
| `aircraft_reg` | Regex: `[A-Z]\d-[A-Z]{2,3}` | `A4O-OCA`, `P4-JAG` |

**Implementation approach:**
```python
class MetadataExtractor:
    def extract(self, cleaned_email: dict) -> dict:
        """Extract all metadata fields from a cleaned email."""

    def extract_request_ids(self, text: str) -> list[str]: ...
    def extract_airports(self, text: str) -> list[str]: ...
    def extract_flight_numbers(self, subject: str, body: str) -> list[str]: ...
    def extract_aircraft_registration(self, text: str) -> list[str]: ...
    def detect_direction(self, from_addr: list[str], to_addr: list[str]) -> str: ...
```

---

### Phase 2b — Email Type Classification

**File:** `metadata/classifier.py`

**Email types (derived from actual data):**

| Type | Signal |
|---|---|
| `slot_request` | Subject contains "Slot Request", from SMB/operators |
| `slot_approval` | "approved", "slot timings noted", from AOCC |
| `slot_conditional` | "shall be confirmed only after you forward us the YA Permit" |
| `landing_permission` | "Landing Permission", LPRQ IDs |
| `flight_schedule` | Tabular flight data, departure/arrival times |
| `ya_submission` | "Please find attached YA" |
| `operational_request` | "Please confirm", "kindly acknowledge" |
| `confirmation` | "Noted", "well noted", "is confirmed" |
| `handling_request` | "HANDLING SERVICES + LANDING PERMIT + SLOTS" |
| `mvt_message` | Subject starts with "MVT:" — movement messages |
| `system_notification` | From IONOS, spam reports |

**Approach:** Start with rule-based classification using subject/body keyword matching. Escalate ambiguous cases to LLM classification.

```python
class EmailClassifier:
    def classify(self, email: dict) -> str:
        """Return email_type string."""

    def classify_by_rules(self, subject: str, body: str) -> str | None: ...
    def classify_by_llm(self, subject: str, body: str) -> str: ...
```

---

### Phase 3 — Entity Extraction

**Goal:** Extract structured business entities for filterable search.

**File:** `metadata/entities.py` ← renamed from `entites.py`

**Entities to extract:**

| Entity | Pattern | Example from data |
|---|---|---|
| Request IDs | `[A-Z]{2,4}RQ-\d{2}-\d{2}-\d{4}-\d{4,5}` | `LPRQ-08-03-2025-48431` |
| Flight Numbers | `[A-Z]{2}\s?\d{3,4}` | `OV 3897`, `JAG1316` |
| Aircraft Registrations | `[A-Z]\d-[A-Z]{2,4}` | `P4-JAG`, `A4O-OCA`, `P4-JMD` |
| ICAO Airport Codes | 4-letter lookup | `VABB`, `OMSJ` |
| IATA Airport Codes | 3-letter lookup | `BOM`, `SHJ`, `RKT`, `KHI`, `MCT` |
| Company Names | NER + keyword list | `Mumbai International Airport Ltd`, `SMB Freight FZE`, `Omega Air`, `SalamAir` |
| Person Names | NER | `Tanisha Sawant`, `Yasar Saquib Shaikh`, `Ibrahim Shaikh` |
| Permission Numbers | Domain-specific regex | Permission reference numbers |
| NOTAM References | `[A-Z]\d{4}/\d{2}` | `A0239/24`, `A1547/23` |
| Phone Numbers | International format regex | `+91 22 66852550` |

**Approach:** Primarily rule-based (regex) extraction for structured IDs, with spaCy or lightweight NER for person/company names.

```python
class EntityExtractor:
    def extract_all(self, email: dict) -> dict:
        """Return entities dict."""

    def extract_request_ids(self, text: str) -> list[str]: ...
    def extract_flight_numbers(self, text: str) -> list[str]: ...
    def extract_aircraft_registrations(self, text: str) -> list[str]: ...
    def extract_airport_codes(self, text: str) -> list[str]: ...
    def extract_notam_refs(self, text: str) -> list[str]: ...
    def extract_persons(self, text: str) -> list[str]: ...
    def extract_companies(self, text: str) -> list[str]: ...
```

**Learning.md topics:**
- NER vs rule-based extraction
- Regex extraction for aviation domain IDs
- Entity normalization and deduplication
- Building domain-specific entity catalogs

---

## Phase 4 — Data & Pipeline Versioning

### Goal

Ensure reproducibility, rollback capability, lineage tracking, and auditability across the entire RAG pipeline.

The objective is to answer questions such as:

* Which cleaned dataset generated the current embeddings?
* Which embedding model was used for indexing?
* What changed between two pipeline runs?
* Can we rollback to a previous dataset or retrieval index?
* Why did retrieval quality change after a deployment?

---

### Tools

#### Git

Used for:

* Source code versioning
* Pipeline logic versioning
* Cleaning logic versioning
* Retrieval logic versioning
* Prompt versioning

---

#### DVC

Used for:

* Dataset versioning
* Pipeline reproducibility
* Data lineage
* Stage dependency tracking
* Dataset rollback

Tracked artifacts:

```text
data/raw
data/cleaned
data/processed
data/embeddings
data/evaluation
```

---

#### params.yaml

Used for configuration versioning.

Example:

```yaml
embedding:
  model_name: BAAI/bge-small-en-v1.5
  batch_size: 64

chunking:
  strategy: email_chunk

retrieval:
  dense_top_k: 100
  sparse_top_k: 100
```

Any configuration change automatically becomes part of the experiment history.

---

#### Qdrant Collection Versioning

Never overwrite production collections.

Create a new collection for every indexing run.

Examples:

```text
knowledge_v1
knowledge_v2
knowledge_v3
```

Use a serving alias:

```text
knowledge_current
```

Application code always queries:

```text
knowledge_current
```

which points to the currently active collection.

---

### Pipeline Lineage

```text
Raw Emails
    ↓
Cleaning
    ↓
Metadata Extraction
    ↓
Entity Extraction
    ↓
Structural Chunking
    ↓
Embeddings
    ↓
Qdrant Collection
```

DVC tracks all dependencies between stages.

If cleaned data changes:

```text
Cleaning
    ↓
Embeddings Invalidated
    ↓
Re-Embedding
    ↓
Reindexing
```

This guarantees consistency between documents and vectors.

---

### DVC Pipeline

Pipeline stages are defined in:

```text
dvc.yaml
```

Example:

```text
raw
    ↓
cleaning
    ↓
metadata
    ↓
chunking
    ↓
embeddings
    ↓
qdrant_ingestion
```

Running:

```bash
dvc repro
```

automatically executes only the stages impacted by upstream changes.

---

### Rollback Strategy

#### Dataset Rollback

```bash
git checkout <commit>
dvc checkout
```

Restores:

* raw data
* cleaned data
* processed data
* embeddings

to the exact state associated with that commit.

---

#### Embedding Rollback

Restore a previous embedding artifact version:

```text
embeddings_v1
embeddings_v2
embeddings_v3
```

through DVC.

---

#### Collection Rollback

Switch serving alias:

```text
knowledge_current
        ↓
knowledge_v2
```

No reindexing required.

No downtime required.

---

### Production Best Practices

* Never overwrite datasets.
* Never overwrite embeddings.
* Never overwrite Qdrant collections.
* Version everything through Git and DVC.
* Store all pipeline configuration in `params.yaml`.
* Rebuild embeddings whenever cleaned data changes.
* Rebuild embeddings whenever embedding model changes.
* Use collection aliases for zero-downtime deployments.
* Maintain reproducible DVC pipelines.

---

### Deliverables

```text
dvc.yaml

params.yaml

data/raw/

data/cleaned/

data/processed/

data/embeddings/

knowledge_v1

knowledge_v2

knowledge_current
```

---

### Learning.md Topics

* Why reproducibility matters in production AI systems
* Git vs DVC responsibilities
* Data lineage and audit trails
* DVC pipelines and dependency graphs
* Embedding reproducibility
* Collection versioning strategies
* Blue-green deployment for vector databases
* Rollback strategies for RAG systems
* Configuration management with params.yaml
* Real-world MLOps versioning patterns

```
```


**Goal:** Track all raw, cleaned, and processed data artifacts, as well as embedding versions and model parameters using **Data Version Control (DVC)** and version manifests for full reproducibility, rollbacks, and pipeline audits.

**Files:**  `dvc.yaml`, `params.yaml`

**DVC Pipeline Design:**
- We will track our dataset files (`data/raw/emails.jsonl`, `data/cleaned/emails.jsonl`, and `data/processed/chunks.jsonl`) using DVC.
- A central `params.yaml` will store pipeline configuration options (e.g. cleaning thresholds, chunk parameters, model names).
- A pipeline file `dvc.yaml` will specify dependencies, outputs, and execution commands for the data cleaning, metadata enrichment, chunking, and vector ingestion stages.

**Document versioning strategy:**
- Each processing run produces a new version: `v1`, `v2`, `v3`
- Store version manifest in `data/versions/manifest.json`
- Track: timestamp, record count, cleaning config hash, changes from previous version

**Embedding versioning strategy:**
- Each embedding run is tagged: `emb_v1`, `emb_v2`
- Track: model name, model version, dimension, total vectors, config hash

**Collection versioning:**
- Qdrant collection naming: `knowledge_v1`, `knowledge_v2`
- Blue-green deployment: create new collection → validate → alias swap


```

**Learning.md topics:**
- Data Version Control (DVC) for machine learning data pipelines
- Reproducible pipelines using `dvc.yaml` and `params.yaml`
- Rollback strategies when embedding quality degrades or collection fails
- Blue-green deployment for zero-downtime reindexing
- Version manifests and audit trails

---

### Phase 5 — Structural Chunking

**Goal:** Preserve email semantics during chunking.

**File:** `ingestion/chunker.py`

**Strategy: 1 Email = 1 Chunk**

Rationale: Emails are already semantic units. The average email body in this dataset is short (typically 50–300 words after cleaning). Splitting would destroy the context of approvals, conditions, and decisions.

**Chunk payload structure:**
```json
{
  "chunk_id":     "sha256_of_email_id",
  "email_id":     "<message-id>",
  "thread_id":    "<root-message-id>",
  "request_id":   "LPRQ-08-03-2025-48431",
  "text":         "subject: RE: Slot Request... body: The slot timings...",
  "email_type":   "slot_approval",
  "status":       "conditional_approval",
  "direction":    "inbound",
  "from":         "aocc.planning@adani.com",
  "to":           ["slots@smb-freight.com"],
  "date":         "2024-05-06T13:33:12+00:00",
  "airports":     ["VABB", "BOM"],
  "flight_numbers": ["OV3897"],
  "aircraft_reg": ["P4-JAG"],
  "companies":    ["Mumbai International Airport Ltd"],
  "persons":      ["Mohak Patwardhan"],
  "document_version":  "v1",
  "embedding_version": "emb_v1"
}
```

**The `text` field** (what gets embedded) should be constructed as:
```
Subject: {subject}
From: {from}
Date: {date}
Body: {body_clean}
```

This gives the embedding model richer context than body alone.

```python
class EmailChunker:
    def chunk(self, enriched_email: dict) -> Chunk: ...
    def build_embedding_text(self, email: dict) -> str: ...
    def generate_chunk_id(self, email_id: str) -> str: ...
```

**Output:** `data/processed/chunks.jsonl`

---

### Phase 6 — Embedding Pipeline

**Goal:** Generate dense and sparse searchable representations.

**File:** `ingestion/embed.py`

**Tech stack decision:**

| Type | Model | Dimension | Why |
|---|---|---|---|
| **Dense** | `BAAI/bge-small-en-v1.5` | 384 | Good quality, fast, small footprint. Upgrade to `bge-base` (768d) if quality insufficient |
| **Sparse** | BM25 via Qdrant's built-in | N/A | Exact keyword matching for aviation codes, IDs, flight numbers |

> Start with `bge-small` for fast iteration. The embedding version system (Phase 4) makes upgrading painless.

**Implementation:**
```python
class EmbeddingPipeline:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model = SentenceTransformer(model_name)

    def embed_dense(self, texts: list[str]) -> np.ndarray: ...
    def validate_embeddings(self, vectors: np.ndarray) -> None:
        """Check for NaN, zero vectors, dimension mismatches."""
    def embed_batch(self, chunks: list[Chunk], batch_size: int = 64) -> list[EmbeddedChunk]: ...
```

**Validation checks:**
- Dimension mismatch (expected vs actual)
- Empty/zero vectors
- NaN values
- Embedding norm sanity check (should be ~1.0 for normalized models)

---

### Phase 7 — Qdrant Ingestion

**Goal:** Store vectors and metadata in Qdrant for retrieval.

**File:** `ingestion/qdrant.py`

**Collection configuration:**
```python
collection_name = "knowledge_v1"

# Dense vector config
dense_config = VectorParams(
    size=384,                    # bge-small dimension
    distance=Distance.COSINE
)

# Sparse vector config (for BM25)
sparse_config = SparseVectorParams(
    modifier=Modifier.IDF       # BM25-style IDF weighting
)
```

**Payload indexes** (for filtered search):
| Field | Index Type | Purpose |
|---|---|---|
| `request_id` | Keyword | Exact match lookups |
| `email_type` | Keyword | Filter by type (slot_approval, etc.) |
| `status` | Keyword | Filter by status |
| `direction` | Keyword | inbound / outbound |
| `date` | Datetime | Date range queries |
| `from` | Keyword | Filter by sender |
| `airports` | Keyword | Filter by airport code |
| `flight_numbers` | Keyword | Filter by flight |
| `aircraft_reg` | Keyword | Filter by aircraft |
| `companies` | Keyword | Filter by company |
| `thread_id` | Keyword | Thread retrieval |

```python
class QdrantManager:
    def __init__(self, url: str, collection_name: str): ...
    def create_collection(self, dense_dim: int) -> None: ...
    def create_payload_indexes(self) -> None: ...
    def upsert_batch(self, points: list[PointStruct], batch_size: int = 100) -> None: ...
    def collection_info(self) -> dict: ...
    def alias_swap(self, alias: str, old_collection: str, new_collection: str) -> None: ...
```

---

### Phase 8 — Query Understanding

**Goal:** Understand user intent and route to the appropriate retrieval strategy.

**File:** `metadata/classifier.py` (extend) + `retrieval/filters.py`

**Intent types:**

| Intent | Example Query | Retrieval Strategy |
|---|---|---|
| `metadata_search` | "Show pending invoices" | Qdrant payload filter only |
| `entity_lookup` | "All emails about P4-JAG" | Payload filter on aircraft_reg |
| `thread_summary` | "Summarize request LPRQ-08-03-2025-48431" | Filter by request_id → collect thread |
| `rag_reasoning` | "Why was landing permission approved?" | Hybrid search + reranking |
| `comparison` | "Compare approval conditions across airports" | Multi-query hybrid search |
| `lifecycle` | "What is the status of flight OV3897?" | Filter + chronological thread assembly |

**Important dependency note:** This phase needs the LLM (Phase 13) for intent classification. Implementation order:
1. Build a simple rule-based intent classifier first (keyword matching)
2. After Phase 13 (LLM client) is done, upgrade to LLM-based classification

```python
class QueryUnderstanding:
    def parse(self, query: str) -> ParsedQuery:
        """Return intent, extracted filters, and reformulated query."""

@dataclass
class ParsedQuery:
    original_query: str
    intent: str                    # metadata_search, rag_reasoning, etc.
    filters: dict                  # {"email_type": "invoice", "status": "pending"}
    entities: dict                 # {"aircraft_reg": "P4-JAG"}
    search_query: str              # Reformulated for embedding search
```

---

### Phase 9 — Retrieval Layer

**Goal:** Retrieve relevant emails using the right strategy per intent.

**File:** `retrieval/hybrid.py`, `retrieval/filters.py`

**Metadata-only search** (for `metadata_search`, `entity_lookup` intents):
```python
# Example: "Show all slot approvals for P4-JAG"
qdrant.scroll(
    filter=Filter(
        must=[
            FieldCondition(key="email_type", match=MatchValue(value="slot_approval")),
            FieldCondition(key="aircraft_reg", match=MatchAny(any=["P4-JAG"]))
        ]
    )
)
```

**Hybrid search** (for `rag_reasoning`, `comparison` intents):
1. Dense retrieval: Top 50 by cosine similarity
2. Sparse retrieval (BM25): Top 50 by keyword match
3. RRF (Reciprocal Rank Fusion): Merge into Top 50

> **Changed from original plan:** Top 100 → Top 50 per channel. With only 699 emails, Top 100 would return ~15% of the entire corpus. Top 50 is more selective while still providing good recall.

```python
class HybridRetriever:
    def search(self, query: str, filters: dict | None, top_k: int = 50) -> list[ScoredEmail]: ...
    def metadata_search(self, filters: dict, limit: int = 50) -> list[dict]: ...
    def dense_search(self, query_vector: list[float], filters: dict | None, top_k: int) -> list: ...
    def sparse_search(self, query: str, filters: dict | None, top_k: int) -> list: ...
    def rrf_fusion(self, dense_results: list, sparse_results: list, k: int = 60) -> list: ...
```

---

### Phase 10 — Cross-Encoder Re-ranking

**Goal:** Improve retrieval quality by re-scoring candidates.

**File:** `retrieval/reranker.py`

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`

**Pipeline:**
- Input: Top 50 from hybrid retrieval
- Process: Score each (query, email_text) pair with cross-encoder
- Output: Top 10 most relevant emails

> For metadata-only queries (exact lookups), skip re-ranking entirely — it adds latency without benefit.

```python
class CrossEncoderReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates: list[ScoredEmail], top_k: int = 10) -> list[ScoredEmail]: ...
    def should_rerank(self, intent: str) -> bool:
        """Skip reranking for metadata_search and entity_lookup intents."""
```

---

### Phase 11 — Context Construction

**Goal:** Assemble high-quality context for the LLM prompt.

**File:** `prompting/builder.py` (part of prompt building)

**Context sources:**
1. **Top re-ranked emails** — direct matches
2. **Thread expansion** — fetch all emails in the same thread_id for complete conversation context
3. **Chronological ordering** — sort by date within each thread

**Context format per email:**
```
[Email 1 of 5] — 2024-05-06T13:33:12Z
From: aocc.planning@adani.com
Type: slot_approval | Status: conditional
---
The slot timings for the proposed flight are noted...
```

**Context budget:** Stay within ~3000 tokens of context to leave room for system prompt + answer generation.

```python
class ContextBuilder:
    def build(self, retrieved_emails: list[ScoredEmail], max_tokens: int = 3000) -> str: ...
    def expand_threads(self, emails: list, qdrant: QdrantManager) -> list: ...
    def format_email_context(self, email: dict, index: int, total: int) -> str: ...
    def truncate_to_budget(self, context: str, max_tokens: int) -> str: ...
```

---

### Phase 12 — Prompt Engineering

**Goal:** Build production prompts that produce grounded, cited answers.

**File:** `prompting/builder.py`

**System prompt template:**
```
You are an Email Intelligence Assistant for SMB Freight FZE aviation operations.

RULES:
1. Answer ONLY using the provided email context. Do not use outside knowledge.
2. If the context does not contain enough information, say so explicitly.
3. Cite the specific email(s) that support your answer using [Email N] format.
4. For timeline/lifecycle questions, present information chronologically.
5. Preserve exact operational details (flight numbers, times, conditions, NOTAM refs).
6. Do not reveal personal contact information (phone numbers, personal emails) unless specifically asked.
```

**Prompt versioning:** Store prompt templates as versioned strings (v1, v2) so changes are trackable and rollbackable.

```python
class PromptBuilder:
    def build(self, query: str, context: str, intent: str) -> list[dict]: ...
    def get_system_prompt(self, intent: str) -> str: ...
    def get_user_prompt(self, query: str, context: str) -> str: ...
```

---

### Phase 13 — LLM Layer

**Goal:** Generate final answers using an LLM.

**File:** `llm/client.py`

**Supported providers (in priority order):**
1. **Google Gemini** (via `google-generativeai` SDK) — `gemini-2.0-flash` for speed, `gemini-2.5-pro` for complex reasoning
2. **OpenAI** (fallback) — `gpt-4o-mini` for cost efficiency

**Implementation:**
```python
class LLMClient:
    def __init__(self, provider: str = "gemini", model: str = "gemini-2.0-flash"):
        ...

    def generate(self, messages: list[dict], temperature: float = 0.1, max_tokens: int = 1024) -> LLMResponse: ...
    def count_tokens(self, text: str) -> int: ...

@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
```

> Temperature should be low (0.1) for factual email intelligence tasks. Higher temperature would introduce hallucination risk.

---

### Phase 14 — Guardrails

**Goal:** Prevent unsafe inputs and outputs.

**Files:** `guardrails/pii.py`, `guardrails/validation.py`

**Input validation:**
- Prompt injection detection (common injection patterns)
- Query length limits
- Empty/malformed query rejection

**Output validation:**
- PII detection: Phone numbers, personal emails in responses (mask unless asked)
- Hallucination check: Verify cited email numbers exist in context
- Grounding validation: Flag answers that don't reference any context emails
- Citation validation: Every claim should map to at least one [Email N] reference

```python
class InputGuard:
    def validate(self, query: str) -> ValidationResult: ...
    def detect_injection(self, query: str) -> bool: ...

class OutputGuard:
    def validate(self, response: str, context: str) -> ValidationResult: ...
    def check_pii(self, response: str) -> list[PIIMatch]: ...
    def check_citations(self, response: str, num_context_emails: int) -> bool: ...
    def mask_pii(self, response: str) -> str: ...
```

---

### Phase 15 — API Layer

**Goal:** Expose system functionality via REST API.

**File:** `service.py` (FastAPI)

**Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/query` | Main query endpoint — accepts natural language, returns grounded answer |
| `POST` | `/ingest` | Trigger re-ingestion pipeline (clean → embed → upsert) |
| `GET` | `/health` | Health check (Qdrant connection, model loaded) |
| `GET` | `/metrics` | Prometheus-compatible metrics |
| `GET` | `/collection/info` | Qdrant collection stats |

**Query request/response:**
```json
// Request
{
  "query": "Why was the slot for P4-JAG approved on Sept 4?",
  "filters": {"aircraft_reg": "P4-JAG"},      // optional
  "top_k": 10                                   // optional
}

// Response
{
  "answer": "The slot for P4-JAG flight JAG1316 on September 4th was confirmed...",
  "citations": [
    {"email_id": "...", "date": "2024-09-03", "snippet": "Slot is confirmed..."}
  ],
  "intent": "rag_reasoning",
  "metadata": {
    "retrieval_latency_ms": 45,
    "llm_latency_ms": 1200,
    "total_latency_ms": 1300,
    "model": "gemini-2.0-flash",
    "tokens_used": 850
  }
}
```

---

### Phase 16 — Observability

**Goal:** Understand system behavior in production.

**Files:** `observability/logging.py`, `observability/metrics.py`, `observability/tracing.py`

**Logging** (structured JSON logs):
- Query received → intent classified → retrieval executed → reranking done → LLM called → response sent
- Error logs with full context for debugging

**Metrics:**
| Metric | Type |
|---|---|
| `retrieval_latency_ms` | Histogram |
| `reranking_latency_ms` | Histogram |
| `llm_latency_ms` | Histogram |
| `total_latency_ms` | Histogram |
| `token_usage_input` | Counter |
| `token_usage_output` | Counter |
| `query_count` | Counter |
| `error_count` | Counter |
| `intent_distribution` | Counter (per intent type) |

**Tracing:**
- Per-request trace ID linking all pipeline stages
- Span hierarchy: Query → Intent → Retrieval → Reranking → Context → LLM → Guardrails → Response

**Implementation:** Use Python `logging` with structured formatters. Optional OpenTelemetry integration for distributed tracing.

---

### Phase 17 — Evaluation

**Goal:** Measure and track system quality.

**Files:** `evaluation/retrieval_eval.py`, `evaluation/rag_eval.py`

**Retrieval evaluation metrics:**
| Metric | Description |
|---|---|
| Recall@10 | % of relevant emails in top 10 |
| Recall@20 | % of relevant emails in top 20 |
| MRR (Mean Reciprocal Rank) | Average reciprocal of first relevant result rank |
| NDCG@10 | Normalized Discounted Cumulative Gain |

**RAG evaluation metrics:**
| Metric | Description |
|---|---|
| Answer Correctness | Does the answer match expected output? |
| Groundedness | Is every claim supported by cited context? |
| Hallucination Rate | % of claims not found in context |
| Citation Accuracy | Do citations point to correct emails? |

**Golden dataset** (store in `data/evaluation/golden.jsonl`):
```json
{
  "query": "Why was the slot for flight OV3897 on March 9 approved?",
  "expected_answer_contains": ["YA copy received", "precondition of having serviceable TOW-BAR"],
  "expected_email_ids": ["<PN2PR01MB90273EC...>"],
  "intent": "rag_reasoning"
}
```

Build 30–50 golden questions covering all intent types, using the actual email data.

---

### Phase 18 — Config & Environment Management [NEW]

**Goal:** Centralized configuration and dependency management.

**File:** `config/settings.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "knowledge_v1"

    # Embedding
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384

    # Reranker
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # LLM
    LLM_PROVIDER: str = "gemini"
    LLM_MODEL: str = "gemini-2.0-flash"
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Retrieval
    DENSE_TOP_K: int = 50
    SPARSE_TOP_K: int = 50
    RERANK_TOP_K: int = 10
    CONTEXT_MAX_TOKENS: int = 3000

    # Email scraping (from existing scraper.py)
    IMAP_HOST: str = ""
    IMAP_PORT: int = 993
    EMAIL_ADDR: str = ""
    EMAIL_PASSWORD: str = ""

    class Config:
        env_file = ".env"
```

**`.env.example`:**
```env
QDRANT_URL=http://localhost:6333
GEMINI_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
IMAP_HOST=imap.ionos.com
EMAIL_ADDR=slots@smb-freight.com
EMAIL_PASSWORD=your-password
```

**`requirements.txt`:**
```
# Core
fastapi>=0.115.0
uvicorn>=0.30.0
pydantic>=2.0
pydantic-settings>=2.0
python-dotenv>=1.0.0

# Data Version Control & Pipelines
dvc>=3.0.0

# Scraping
beautifulsoup4>=4.12.0

# Embeddings & ML
sentence-transformers>=3.0.0
torch>=2.0.0

# Vector store
qdrant-client>=1.12.0

# LLM
google-generativeai>=0.8.0
openai>=1.50.0

# NER (optional, for entity extraction)
spacy>=3.7.0

# Evaluation
ragas>=0.2.0

# Observability
structlog>=24.0.0

# Testing
pytest>=8.0.0
```

**`.gitignore`:**
```
venv/
__pycache__/
*.pyc
.env
*.log
data/raw/
*.progress
.idea/
.vscode/
```

---

## Structural Fixes Required

| Fix | Details |
|---|---|
| Rename `metadata/entites.py` → `metadata/entities.py` | Typo fix |
| Rename `versioning/leaning.md` → `versioning/learning.md` | Typo fix |
| Rename `ingestion/learning` → `ingestion/learning.md` | Missing extension |
| Add `__init__.py` to all modules | Makes them importable as Python packages |
| Add `config/` directory | Centralized settings |
| Add `tests/` directory | Test suite |
| Populate `requirements.txt` | Pin all dependencies |
| Populate `.gitignore` | Exclude venv, data, secrets |
| Add `.env.example` | Document required environment variables |

---

## Dependency Graph & Build Order

```
Phase 18 (Config)  ─────────────────────────┐
                                             │
Phase 0 (Scraping) ✅                        │
     ↓                                       │
Phase 1 (Cleaning)                           │
     ↓                                       │
Phase 2 (Metadata) + Phase 3 (Entities)      │  ← can be parallel
     ↓                                       │
Phase 4 (Versioning)                         │
     ↓                                       │
Phase 5 (Chunking)                           │
     ↓                                       │
Phase 6 (Embedding)                          │
     ↓                                       │
Phase 7 (Qdrant Ingestion)                   │
     ↓                                       │
Phase 13 (LLM Client) ──────────────────────┤  ← needed before Phase 8
     ↓                                       │
Phase 8 (Query Understanding)                │
     ↓                                       │
Phase 9 (Retrieval) + Phase 10 (Reranking)   │
     ↓                                       │
Phase 11 (Context) + Phase 12 (Prompting)    │
     ↓                                       │
Phase 14 (Guardrails)                        │
     ↓                                       │
Phase 15 (API Layer)                         │
     ↓                                       │
Phase 16 (Observability) ───────────────────┘  ← weave throughout
     ↓
Phase 17 (Evaluation)  ← last, needs working system
```

**Recommended implementation order:**
1. Phase 18 → Config & environment setup
2. Phase 1 → Cleaning (start processing data)
3. Phase 2 + 3 → Metadata + entities (enrich data)
4. Phase 5 → Chunking (prepare for embedding)
5. Phase 6 + 7 → Embedding + Qdrant (get data searchable)
6. Phase 13 → LLM client (needed for query understanding)
7. Phase 8 → Query understanding
8. Phase 9 + 10 → Retrieval + reranking
9. Phase 11 + 12 → Context + prompting
10. Phase 14 → Guardrails
11. Phase 15 → API layer (integrate everything)
12. Phase 4 → Versioning (once pipeline is stable)
13. Phase 16 → Observability (instrument everything)
14. Phase 17 → Evaluation (measure quality)

---

## Future Enhancements (Phase 19+)

| Enhancement | Value |
|---|---|
| Query Rewriting | Expand ambiguous queries for better retrieval |
| Multi-Query Retrieval | Generate multiple search queries from one user question |
| SPLADE | Learned sparse representations instead of BM25 |
| Agentic Retrieval | LLM-driven iterative retrieval (search → reflect → search again) |
| Semantic Caching | Cache frequent query→answer pairs |
| Knowledge Graphs | Model relationships between entities (flights, companies, airports) |
| Multi-Tenant Support | Isolate data per organization |
| RBAC | Role-based access control for sensitive emails |
| Feedback Learning | Use user feedback to improve retrieval and ranking |
| Workflow State Tracking | Track request lifecycle state machines |
| Attachment Processing | Extract text from PDF/Excel attachments |

---

## Success Criteria

The system should answer questions such as:

* Why was landing permission approved?
* What conditions were attached to approval?
* Summarize all communication for request X.
* What actions are pending for request Y?
* Compare approval requirements across requests.
* Explain the complete lifecycle of request Z.
* Identify recurring operational requirements.
* Generate a summary report for a company or flight.
* What NOTAMs affected flights to BOM in September 2024?
* Which flights required DGCA approval?
* Show all slot approvals for aircraft P4-JAG.

> **The primary objective is not email search. The primary objective is transforming historical email communication into an explainable knowledge system capable of reasoning over operational decisions and workflows.**
