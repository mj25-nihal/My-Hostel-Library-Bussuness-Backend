"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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
from core.views_revenue import RevenueSummaryView
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from rest_framework.routers import DefaultRouter
from core.views import (
    ComplaintViewSet, SuggestionViewSet, ReviewViewSet, ContactMessageViewSet,
    hostel_booking_history_by_student, library_booking_history_by_student, export_hostel_bookings_csv_by_student,
    export_library_bookings_csv_by_student, student_full_profile, download_student_profile_pdf, AchievementBlogViewSet
)
from core.views import hostel_booking_history_by_student, library_booking_history_by_student, send_email_to_students
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


schema_view = get_schema_view(
    openapi.Info(
        title="Hostel & Library Management API",
        default_version='v1',
        description="API documentation for Hostel and Library",
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

router = DefaultRouter()
router.register('complaints', ComplaintViewSet)
router.register('suggestions', SuggestionViewSet)
router.register('reviews', ReviewViewSet, basename='reviews')
router.register(r'contactus', ContactMessageViewSet, basename='contactus')
router.register('achievements', AchievementBlogViewSet)


urlpatterns = [
    path('api/', include(router.urls)),

    # path('', include(router.urls)),
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/users/', include('users.urls')),
    path('api/hostel/', include('hostel.urls')),
    path('api/library/', include('library.urls')),

    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    path('hostel-booking-history/<int:student_id>/', hostel_booking_history_by_student),
    path('library-booking-history/<int:student_id>/', library_booking_history_by_student),
    path('hostel-booking-history/export/', export_hostel_bookings_csv_by_student),
    path('library-booking-history/export/', export_library_bookings_csv_by_student),

    path('api/admin/students/<int:student_id>/full-profile/', student_full_profile),
    path('api/admin/students/<int:student_id>/full-profile/pdf/', download_student_profile_pdf),

    path('api/admin/send-email/', send_email_to_students, name='admin-send-email'),

    path('api/admin/revenue-summary/', RevenueSummaryView.as_view(), name='revenue-summary'),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
