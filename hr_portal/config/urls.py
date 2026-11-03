from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("portal.biometric_urls")),      # biometric machines (before /api/ so nothing can shadow it)
    path("api/", include("portal.api_urls")),
    path("", include("portal.urls")),
]
