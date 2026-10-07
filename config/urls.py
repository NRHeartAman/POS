from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = 'CraveCast POS Admin'
admin.site.site_title  = 'CraveCast POS'

urlpatterns = [
    path('admin/',  admin.site.urls),
    path('login/',  auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('',        include('pos.urls')),
]
