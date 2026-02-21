"""
Root URL configuration for igdm project.
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('instagram/', include('instagram.urls')),
    path('automations/', include('automations.urls')),
    path('webhook/', include('webhooks.urls')),
    path('dashboard/', include('dashboard.urls')),
    # Root redirect
    path('', lambda request: redirect('dashboard:home')),
]
