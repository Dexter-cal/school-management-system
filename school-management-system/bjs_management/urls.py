"""
URL configuration for bjs_management project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from django.http import HttpResponse

def security_txt(request):
    content = """Contact: mailto:security@bitende.com
Expires: 2027-12-31T23:59:59.000Z
Preferred-Languages: en
"""
    return HttpResponse(content, content_type="text/plain")

urlpatterns = [
    path(".well-known/security.txt", security_txt),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/google/", include("allauth.socialaccount.providers.google.urls")),
    path("", include("school.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
