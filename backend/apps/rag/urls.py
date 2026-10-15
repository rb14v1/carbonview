from django.urls import path
from .views import ask_ai, chart_data, suggested_questions


urlpatterns = [
    path('ask/', ask_ai),
    path('chart/', chart_data),
    path('suggestions/', suggested_questions),
]
