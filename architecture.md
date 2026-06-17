Emails
   ↓
Cleaning
   ↓
Metadata Extraction
   ↓
Entity Extraction
   ↓
Structural Chunking
(1 email = 1 chunk)
   ↓
Dense Embeddings
   ↓
Sparse Embeddings
   ↓
Qdrant

----------------------------------

User Query
   ↓
Intent Understanding
   ↓

Metadata Filters
(request id,
company,
person,
status)

   ↓

Hybrid Retrieval
(Dense + BM25)

   ↓

Cross Encoder

   ↓

Context Builder

   ↓

LLM

   ↓

Grounding Validation

   ↓

Response