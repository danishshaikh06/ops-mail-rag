from .hybrid import HybridRetriever

r = HybridRetriever(qdrant_url="http://localhost:6333", collection_name="knowledge_v4")

# Hybrid search (same as before)
results = r.search("NOC from MoCA to operate cargo flight at VAOZ airport", top_k=10)

# NEW: pure metadata filter, no embedding at all
slot_approvals = r.metadata_search(filters={"email_type": "slot_approval"}, limit=20)

# NEW: filtered hybrid search — combine semantic + metadata
results_filtered = r.search("approval conditions", filters={"aircraft_registrations": ["A4O-OCA"]}, top_k=10)

threads = r.expand_threads(results_filtered)

#print("Hybrid Search Results:")
#for res in results:
 #   print(res) 

print("\nFiltered Hybrid Search Results:")
for res in results_filtered:
    print(res) 

#print("\nExpanded Threads:")
#for thread in threads:
 #   print(thread)

#print("\nMetadata Search Results (Slot Approvals):")
#for res in slot_approvals:
    #print(res)