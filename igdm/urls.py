"""
Root URL configuration for igdm project.
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('instagram/', include('instagram.urls')),
    path('automations/', include('automations.urls')),
    path('webhook/', include('webhooks.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('scheduler/', include('scheduler.urls')),
    # Root redirect
    path('', lambda request: redirect('dashboard:home')),
]+static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Serve uploaded media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
