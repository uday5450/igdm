"""Automations app — URL configuration."""
from django.urls import path
from . import views

app_name = 'automations'

urlpatterns = [
    path('', views.automation_list, name='list'),
    path('create/', views.automation_create, name='create'),
    path('<int:automation_id>/', views.automation_detail, name='detail'),
    path('<int:automation_id>/toggle/', views.automation_toggle, name='toggle'),
    path('<int:automation_id>/delete/', views.automation_delete, name='delete'),
    path('<int:automation_id>/dry-run/', views.automation_dry_run, name='dry_run'),
]
