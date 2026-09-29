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
    path('leads/', views.leads, name='leads'),
    path('leads/<int:pk>/reset-link/', views.reset_link_create, name='reset_link_create'),
    path('reset/<uidb64>/<token>/', views.PulseResetConfirmView.as_view(), name='password_reset_confirm'),
    path('invite/<str:token>/', views.invite, name='invite'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/', views.project_trend, name='project_trend'),
    path('projects/<int:pk>/delete/', views.project_delete, name='project_delete'),
    path('p/<str:token>/', views.respond, name='respond'),
    path('p/<str:token>/thanks/', views.respond_thanks, name='respond_thanks'),
    path('health/', views.health, name='health'),
]
