from rest_framework import generics, permissions
from .serializers import RegisterSerializer, CustomTokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.views import APIView
from rest_framework import status
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.conf import settings
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth import get_user_model
from .serializers import UserSerializer
from hostel.models import HostelBooking
from library.models import LibraryBooking
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes,parser_classes
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

User = get_user_model()


#Register View
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    @swagger_auto_schema(
        request_body=RegisterSerializer,
        responses={201: "User registered successfully", 400: "Validation failed"}
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


#Custom Token Serializer (adds role and username)
class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # 👇 Custom claims
        token['username'] = user.username
        token['role'] = user.role
        token['full_name'] = f"{user.first_name} {user.last_name}"

        return token


#Custom Token View (for login)
class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer

    @swagger_auto_schema(
        operation_description="Login to get access & refresh tokens",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['username', 'password'],
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING),
                'password': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={200: "JWT tokens", 401: "Invalid credentials"}
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


#Optional: Another custom token serializer
class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


#CSRF-exempt password reset view
class CustomPasswordResetView(APIView):
    permission_classes = [permissions.AllowAny]

    @swagger_auto_schema(
        operation_description="Send password reset email",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["email"],
            properties={"email": openapi.Schema(type=openapi.TYPE_STRING)}
        ),
        responses={200: "Reset link sent", 404: "Email not found"}
    )
    def post(self, request):
        email = request.data.get('email')
        try:
            user = User.objects.get(email=email)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}/"
            send_mail(
                subject='Password Reset',
                message=f'Click here to reset your password:\n\n{reset_url}',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
            )
            return Response({'message': 'Reset link sent'}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'error': 'Email not found'}, status=status.HTTP_404_NOT_FOUND)


@method_decorator(csrf_exempt, name='dispatch')
class SetNewPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    def post(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
            if not default_token_generator.check_token(user, token):
                return Response({"error": "Invalid or expired token."}, status=400)

            password1 = request.data.get("new_password1")
            password2 = request.data.get("new_password2")

            if password1 != password2:
                return Response({"error": "Passwords do not match."}, status=400)

            user.set_password(password1)
            user.save()
            return Response({"message": "Password reset successful."})
        except:
            return Response({"error": "Something went wrong."}, status=400)

@swagger_auto_schema(
    method='get',
    operation_description="Get currently logged-in user profile including hostel/library booking info",
    responses={200: UserSerializer}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_logged_in_user(request):
    user = request.user
    serializer = UserSerializer(user, context={'request': request})
    user_data = serializer.data

    # Aadhaar defaults
    aadhaar_front_photo = None
    aadhaar_back_photo = None

    # Hostel Booking
    hostel_booking = HostelBooking.objects.filter(student=user, status__in=['approved', 'pending']).last()
    if hostel_booking:
        user_data['hostel_room'] = hostel_booking.bed.room.room_number if hostel_booking.bed else None
        user_data['hostel_bed'] = hostel_booking.bed.bed_number if hostel_booking.bed else None
        user_data['hostel_booking_id'] = hostel_booking.id
        user_data['hostel_booking_status'] = hostel_booking.status

        if hostel_booking.aadhaar_front_photo:
            aadhaar_front_photo = request.build_absolute_uri(hostel_booking.aadhaar_front_photo.url)
        if hostel_booking.aadhaar_back_photo:
            aadhaar_back_photo = request.build_absolute_uri(hostel_booking.aadhaar_back_photo.url)
    else:
        user_data['hostel_booking_id'] = None
        user_data['hostel_booking_status'] = None

    # Library Booking
    library_booking = LibraryBooking.objects.filter(student=user, status__in=['approved', 'pending']).last()
    if library_booking:
        user_data['library_seat'] = library_booking.seat.seat_number if library_booking.seat else None
        user_data['library_booking_id'] = library_booking.id
        user_data['library_booking_status'] = library_booking.status

        if not aadhaar_front_photo and library_booking.aadhaar_front_photo:
            aadhaar_front_photo = request.build_absolute_uri(library_booking.aadhaar_front_photo.url)
        if not aadhaar_back_photo and library_booking.aadhaar_back_photo:
            aadhaar_back_photo = request.build_absolute_uri(library_booking.aadhaar_back_photo.url)
    else:
        user_data['library_booking_id'] = None
        user_data['library_booking_status'] = None

    # Attach Aadhaar to response
    user_data['aadhaar_front_photo'] = aadhaar_front_photo
    user_data['aadhaar_back_photo'] = aadhaar_back_photo

    return Response(user_data)




@swagger_auto_schema(
    method='patch',
    operation_description="Update profile photo (multipart form)",
    manual_parameters=[
        openapi.Parameter(
            name='profile_photo',
            in_=openapi.IN_FORM,
            type=openapi.TYPE_FILE,
            required=True,
            description='Profile photo file'
        )
    ]
)
@api_view(['PATCH'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def update_profile_photo(request):
    user = request.user
    photo = request.FILES.get('profile_photo')
    if photo:
        user.profile_photo = photo
        user.save()
        return Response({"detail": "Profile photo updated successfully."})
    return Response({"error": "No file uploaded."}, status=400)


@swagger_auto_schema(
    method='patch',
    operation_description="User/Student can deactivate their own profile (soft delete)",
    responses={200: "User deactivated", 403: "Unauthorized", 404: "User not found"}
)
@api_view(['PATCH'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def delete_own_profile(request):
    user = request.user
    user.is_active = False  # soft delete
    user.save()
    return Response({"detail": "Profile deactivated successfully."}, status=200)



#Admin delete any profile by ID
@swagger_auto_schema(
    method='delete',
    operation_description="Admin can deactivate (soft delete) any user by ID",
    responses={200: "User deactivated", 403: "Unauthorized", 404: "User not found"}
)
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_user_by_id(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'Only admin can deactivate users.'}, status=403)

    try:
        user = User.objects.get(id=user_id)
        user.is_active = False  # soft delete
        user.save()
        return Response({'detail': 'User deactivated successfully.'})
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)

@swagger_auto_schema(
    method='post',
    operation_description="Admin can reactivate a deactivated student by ID",
    responses={200: "User activated", 403: "Unauthorized", 404: "User not found"}
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def activate_user_by_id(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'Only admin can activate users.'}, status=403)

    try:
        user = User.objects.get(id=user_id)
        user.is_active = True  # reactivate
        user.save()
        return Response({'detail': 'User activated successfully.'})
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)


from rest_framework import filters
from django.db.models import Q

@swagger_auto_schema(
    method='get',
    operation_description="Admin can get list of all student users (supports search and status filter)",
    manual_parameters=[
        openapi.Parameter('search', openapi.IN_QUERY, description="Search by ID, name, phone, email, education", type=openapi.TYPE_STRING),
        openapi.Parameter('status', openapi.IN_QUERY, description="Filter by status: active or inactive", type=openapi.TYPE_STRING)
    ],
    responses={200: UserSerializer(many=True)}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_all_students(request):
    if request.user.role != 'admin':
        return Response({'error': 'Only admin can view student list'}, status=403)

    search = request.query_params.get('search', '').lower()
    status_filter = request.query_params.get('status')

    students = User.objects.filter(role='student')

    if status_filter == 'active':
        students = students.filter(is_active=True)
    elif status_filter == 'inactive':
        students = students.filter(is_active=False)

    if search:
        try:
            search_id = int(search)
            students = students.filter(
                Q(id=search_id) |
                Q(first_name__icontains=search) |
                Q(middle_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(education__icontains=search)
            )
        except ValueError:
            students = students.filter(
                Q(first_name__icontains=search) |
                Q(middle_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(education__icontains=search)
            )

    data = []
    for student in students:
        user_data = UserSerializer(student, context={'request': request}).data

        # Hostel Booking ID
        hostel_booking = HostelBooking.objects.filter(student=student, status__in=['approved', 'pending']).last()
        user_data['hostel_booking_id'] = hostel_booking.id if hostel_booking else None

        # Library Booking ID
        library_booking = LibraryBooking.objects.filter(student=student, status__in=['approved', 'pending']).last()
        user_data['library_booking_id'] = library_booking.id if library_booking else None

        data.append(user_data)

    return Response(data)



@swagger_auto_schema(
    method='get',
    operation_description="Set CSRF cookie (frontend integration)",
    responses={200: "CSRF cookie set"}
)
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
@ensure_csrf_cookie
def csrf_cookie_view(request):
    return Response({"message": "CSRF cookie set."})


@swagger_auto_schema(
    method='patch',
    manual_parameters=[
        openapi.Parameter('phone_number', openapi.IN_FORM, type=openapi.TYPE_STRING, required=False),
        openapi.Parameter('email', openapi.IN_FORM, type=openapi.TYPE_STRING, required=False),
        openapi.Parameter('address', openapi.IN_FORM, type=openapi.TYPE_STRING, required=False),
        openapi.Parameter('education', openapi.IN_FORM, type=openapi.TYPE_STRING, required=False),
        openapi.Parameter('profile_photo', openapi.IN_FORM, type=openapi.TYPE_FILE, required=False),
    ],
    operation_description="Update student's own profile (supports photo upload too)"
)

@api_view(['PATCH'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def update_student_profile(request):
    user = request.user

    # Fields to update
    user.phone_number = request.data.get('phone_number', user.phone_number)
    user.email = request.data.get('email', user.email)
    user.address = request.data.get('address', user.address)
    user.education = request.data.get('education', user.education)

    # Optional: handle image
    if 'profile_photo' in request.FILES:
        user.profile_photo = request.FILES['profile_photo']

    user.save()
    return Response({"detail": "Profile updated successfully."})
