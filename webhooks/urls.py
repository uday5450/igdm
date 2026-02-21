"""Webhooks app — URL configuration."""
from django.urls import path
from . import views

app_name = 'webhooks'

urlpatterns = [
    path('instagram/', views.webhook_handler, name='instagram'),
]
