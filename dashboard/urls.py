"""Dashboard app — URL configuration."""
from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('contacts/', views.contacts_view, name='contacts'),
    path('settings/', views.settings_view, name='settings'),
]
