from .hybrid import HybridRetriever
from .reranker import rerank

retriever = HybridRetriever(qdrant_url="http://localhost:6333", collection_name="knowledge_v4")
results = retriever.search("NOC from MoCA to operate cargo flight at VAOZ airport", top_k=10)

top_results = rerank("NOC from MoCA to operate cargo flight at VAOZ airport", results, top_k=3)

for r in top_results:
    print(f"{r['score']:.4f} | {r['payload']['text'][:80]}")