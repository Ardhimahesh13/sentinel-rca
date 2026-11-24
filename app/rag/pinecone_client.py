from functools import lru_cache
from typing import Any,Literal
from pinecone import Pinecone
from app.core.config import get_settings

class PineconeRunbookStore :
    def __init__(self) -> None :
        settings = get_settings()
        self.pc =  Pinecone(api_key = settings.PINECONE_API_KEY)
        self.index_name = settings.PINECONE_INDEX_NAME
        self.embed_model = settings.PINECONE_EMBED_MODEL
        self.index = self.pc.Index(self.index_name)

    def embed_texts(
            self,
            texts :list[str],
            input_type : Literal['passage','query'] = "passage",
    ) ->list[list[float]] :
        response = self.pc.inference.embed(
            model = self.embed_model,
            inputs = texts,
            parameters = {"input_type" : input_type},
        )
        return [item.values for item in response]

    def upsert_runbooks(
        self,
        documents: list[dict[str, Any]],
        namespace: str = "runbooks",
    ) -> int:
        """
        Embed and upsert runbook documents.
        Each doc must have: id, text, and metadata (dict).
        """
        texts = [doc["text"] for doc in documents]
        vectors = self.embed_texts(texts, input_type="passage")

        records = []
        for doc, vec in zip(documents, vectors):
            metadata = {**doc.get("metadata", {}), "text": doc["text"]}
            records.append({"id": doc["id"], "values": vec, "metadata": metadata})

        self.index.upsert(vectors=records, namespace=namespace)
        return len(records)

    def search_runbooks(
        self,
        query: str,
        top_k: int = 3,
        domain_filter: str | None = None,
        namespace: str = "runbooks",
    ) -> list[dict[str, Any]]:
        """Semantic search over historical post-mortems and runbooks."""
        query_vector = self.embed_texts([query], input_type="query")[0]
        metadata_filter = {"domain": {"$eq": domain_filter}} if domain_filter else None

        result = self.index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
            namespace=namespace,
            filter=metadata_filter,
        )

        matches = []
        for match in result.matches:
            matches.append(
                {
                    "id": match.id,
                    "score": round(match.score, 4),
                    "title": match.metadata.get("title", "Untitled"),
                    "domain": match.metadata.get("domain", "general"),
                    "text": match.metadata.get("text", ""),
                }
            )
        return matches


@lru_cache
def get_runbook_store() -> PineconeRunbookStore:
    return PineconeRunbookStore()
    