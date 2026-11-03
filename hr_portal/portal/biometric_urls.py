from django.urls import path

from . import biometric_api

urlpatterns = [
    path("api/biometric/punch/", biometric_api.punch, name="biometric_punch"),
    path("iclock/cdata", biometric_api.adms_cdata, name="adms_cdata"),
    path("iclock/getrequest", biometric_api.adms_getrequest, name="adms_getrequest"),
]
