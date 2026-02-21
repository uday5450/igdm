"""Instagram app — URL configuration."""
from django.urls import path
from . import views

app_name = 'instagram'

urlpatterns = [
    path('connect/', views.connect_instagram, name='connect'),
    path('callback/', views.instagram_callback, name='callback'),
    path('disconnect/<int:account_id>/', views.disconnect_instagram, name='disconnect'),
    path('switch/<int:account_id>/', views.switch_account, name='switch'),
]
