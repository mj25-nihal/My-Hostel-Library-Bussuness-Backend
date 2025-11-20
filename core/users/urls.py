from django.urls import path
from .views import RegisterView, MyTokenObtainPairView, CustomPasswordResetView, SetNewPasswordView, get_logged_in_user, \
    update_profile_photo, delete_own_profile, delete_user_by_id, list_all_students, csrf_cookie_view, \
    update_student_profile, activate_user_by_id
from rest_framework_simplejwt.views import TokenRefreshView
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Auth
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Password Reset
    path('password_reset/', CustomPasswordResetView.as_view(), name='password_reset'),  # POST email
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password_reset/', CustomPasswordResetView.as_view(), name='password_reset'),
    path('reset/<uidb64>/<token>/', SetNewPasswordView.as_view(), name='set_new_password'),
    path('csrf-cookie/', csrf_cookie_view, name='csrf_cookie'),

    # Profile & Users
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('reset/<uidb64>/<token>/', SetNewPasswordView.as_view(), name='set_new_password'),
    path('me/', get_logged_in_user, name='get_logged_in_user'),
    path('update-profile-photo/', update_profile_photo),
    path('delete-profile/', delete_own_profile, name='delete_profile'),
    path('delete-user/<int:user_id>/', delete_user_by_id, name='delete_user_by_id'),
    path('students/', list_all_students, name='list_all_students'),
    path('update-profile/', update_student_profile, name='update_student_profile'),
    path('activate-user/<int:user_id>/', activate_user_by_id, name='activate_user_by_id'),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
