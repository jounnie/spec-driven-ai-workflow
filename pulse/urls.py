from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('login/', views.PulseLoginView.as_view(), name='login'),
    path('logout/', views.PulseLogoutView.as_view(), name='logout'),
    path('health/', views.health, name='health'),
]
