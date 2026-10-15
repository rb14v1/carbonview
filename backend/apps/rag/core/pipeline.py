from typing import Any


class RAGPipeline:
    def __init__(self, retriever: Any, formatter: Any, builder: Any):
        """Store the pluggable components that make up a RAG workflow."""
        self.retriever = retriever
        self.formatter = formatter
        self.builder = builder

    def run(self, query, scope=None, history=None):
        """Retrieve relevant documents for a query and format the final answer."""
        try:
            documents = self.retriever.search(query, scope=scope)
        except Exception:
            documents = []

        try:
            return self.formatter.format(query, documents, history)
        except Exception:
            fallback_answer = documents[0].content if documents else "I could not generate an answer right now."
            return fallback_answer, "pipeline-local-fallback"
