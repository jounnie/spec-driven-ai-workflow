from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('login/', views.PulseLoginView.as_view(), name='login'),
    path('logout/', views.PulseLogoutView.as_view(), name='logout'),
    path('invitations/', views.invitations, name='invitations'),
    path('invitations/create/', views.invitation_create, name='invitation_create'),
    path('invitations/<int:pk>/revoke/', views.invitation_revoke, name='invitation_revoke'),
    path('invite/<str:token>/', views.invite, name='invite'),
    path('health/', views.health, name='health'),
]
