"""Scheduler app — URL configuration."""
from django.urls import path
from . import views

app_name = 'scheduler'

urlpatterns = [
    path('', views.scheduled_list, name='list'),
    path('create/', views.scheduled_create, name='create'),
    path('<int:post_id>/', views.scheduled_detail, name='detail'),
    path('<int:post_id>/delete/', views.scheduled_delete, name='delete'),
]
