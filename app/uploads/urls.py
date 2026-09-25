from django.urls import path

from . import views

urlpatterns = [
    path('', views.lista_documentos, name='lista_documentos'),
]
