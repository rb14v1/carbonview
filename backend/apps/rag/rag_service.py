from .answering import generate_answer
from .charting import generate_chart_payload
from .core import RAGPipeline
from .core.answering import CarbonFormatter, Formatter, rewrite_query_with_history
from .document_builders import CarbonDocumentBuilder, DocumentBuilder, get_document_builder
from .retrieval import get_default_retriever, search
from .types import ChatTurn, RetrievedDocument, SearchScope


default_builder = get_document_builder()
default_formatter = CarbonFormatter()
default_pipeline = RAGPipeline(
    retriever=get_default_retriever(),
    formatter=default_formatter,
    builder=default_builder,
)


def run(query: str, scope: SearchScope | None = None, history: list[ChatTurn] | None = None):
    """Run the default CarbonView RAG pipeline end to end."""
    return default_pipeline.run(query, scope=scope, history=history)


__all__ = [
    "RetrievedDocument",
    "SearchScope",
    "ChatTurn",
    "DocumentBuilder",
    "CarbonDocumentBuilder",
    "Formatter",
    "CarbonFormatter",
    "RAGPipeline",
    "default_pipeline",
    "run",
    "generate_answer",
    "generate_chart_payload",
    "rewrite_query_with_history",
    "search",
]
