from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),              # ✅ for admin panel access
    path('api/', include('core.urls')),           # ✅ for your core APIs
]
