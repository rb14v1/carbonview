from rest_framework.decorators import api_view
from rest_framework.response import Response

from .agent import QueryRouter
from .charting import build_chart_payload_from_sql_result, generate_chart_payload
from .core.orchestrator import build_suggested_questions, handle_ask_ai, handle_chart_data, resolve_scope
from .rag_service import generate_answer, rewrite_query_with_history, search
from .sql_tool import SQLTool


router = QueryRouter()
sql_tool = SQLTool()


@api_view(["POST"])
def ask_ai(request):
    return handle_ask_ai(
        request,
        router=router,
        sql_tool=sql_tool,
        search_fn=search,
        generate_answer_fn=generate_answer,
        rewrite_query_with_history_fn=rewrite_query_with_history,
        build_chart_payload_from_sql_result_fn=build_chart_payload_from_sql_result,
    )


@api_view(["GET", "POST"])
def suggested_questions(request):
    scope = resolve_scope(request)
    return Response({"questions": build_suggested_questions(scope)})


@api_view(["POST"])
def chart_data(request):
    return handle_chart_data(
        request,
        generate_chart_payload_fn=generate_chart_payload,
        rewrite_query_with_history_fn=rewrite_query_with_history,
    )
