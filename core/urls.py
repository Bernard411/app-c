# urls.py - Add these to your Django URLs

from django.urls import path
from . import service_finder_api, views

urlpatterns = [
    path('api/peza/', service_finder_api.peza_api, name='peza_api'),
    path('api/health/', service_finder_api.health_check, name='health_check'),
    path('api/emergency-alert/', service_finder_api.emergency_alert, name='emergency_alert'),
    path('', views.home, name='home'),
]
