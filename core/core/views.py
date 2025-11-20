from rest_framework import viewsets, permissions, status
from .models import Complaint, Suggestion, Review, ContactMessage
from .serializers import ComplaintSerializer, SuggestionSerializer, ReviewSerializer, ContactMessageSerializer
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser
from core.permissions import IsStudentOnly
from rest_framework.decorators import action
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.permissions import IsAuthenticated
from hostel.models import HostelBooking
from library.models import LibraryBooking
from rest_framework.decorators import api_view, permission_classes
from .models import Complaint, Review, AchievementBlog
from .serializers import ComplaintSerializer, ReviewSerializer
from hostel.serializers import HostelBookingSerializer
from library.serializers import LibraryBookingSerializer
from django.http import HttpResponse
from core.utils.pdf_utils import generate_student_profile_pdf
from core.serializers import AdminHostelBookingSerializer, AdminLibraryBookingSerializer, AdminSendEmailSerializer, \
    AchievementBlogSerializer
from .serializers import AdminSendEmailSerializer
from users.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.core.mail import EmailMessage
import threading


class IsStudentOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'student'


class ComplaintViewSet(viewsets.ModelViewSet):
    queryset = Complaint.objects.all().order_by('-submitted_on')
    serializer_class = ComplaintSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.IsAuthenticated(), IsStudentOnly()]
        elif self.action == 'resolve':
            return [permissions.IsAuthenticated()]  # allow both student and admin
        elif self.request.user.is_authenticated and self.request.user.role == 'admin':
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]  # fallback

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Complaint.objects.none()
        if user.role == 'admin':
            return Complaint.objects.all().order_by('-submitted_on')
        if user.role == 'student':
            return Complaint.objects.filter(submitted_by=user).order_by('-submitted_on')
        return Complaint.objects.none()

    @swagger_auto_schema(
        method='post',
        operation_description="Mark complaint as resolved (Student or Admin)",
        responses={
            200: openapi.Response("Complaint marked as resolved."),
            400: openapi.Response("Already resolved")
        }
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def resolve(self, request, pk=None):
        complaint = self.get_object()
        if complaint.status == 'resolved':
            return Response({"detail": "Already marked as resolved."}, status=400)
        complaint.status = 'resolved'
        complaint.save()
        return Response({"detail": "Complaint marked as resolved."}, status=200)


class SuggestionViewSet(viewsets.ModelViewSet):
    queryset = Suggestion.objects.all().order_by('-submitted_on')
    serializer_class = SuggestionSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(submitted_by=user)

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and user.role == 'admin':
            return Suggestion.objects.all().order_by('-submitted_on')
        return Suggestion.objects.none()


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all().order_by('-submitted_on')
    serializer_class = ReviewSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.IsAuthenticated(), IsStudentOnly()]
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and user.role == 'admin':
            return Review.objects.all().order_by('-submitted_on')
        if user.is_authenticated and user.role == 'student':
            return Review.objects.filter(name=user.username)
        return Review.objects.filter(is_approved=True).order_by('-submitted_on')

    @swagger_auto_schema(
        request_body=ReviewSerializer,
        responses={
            201: openapi.Response("Review submitted. Awaiting admin approval."),
            400: "Validation error or already submitted"
        }
    )
    def create(self, request, *args, **kwargs):
        user = request.user
        if Review.objects.filter(name=user.username).exists():
            return Response(
                {"detail": "You have already submitted a review."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(name=user.username, is_approved=False)
            return Response(
                {"detail": "Review submitted. Awaiting admin approval."},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        return Response({"detail": "Updating reviews is not allowed."}, status=403)

    def partial_update(self, request, *args, **kwargs):
        return Response({"detail": "Updating reviews is not allowed."}, status=403)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"detail": "Review deleted successfully."}, status=200)

    @swagger_auto_schema(
        method='post',
        operation_description="Approve a pending review (Admin only)",
        responses={200: "Review approved", 400: "Already approved"}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        review = self.get_object()
        if review.is_approved:
            return Response({"detail": "Review already approved."}, status=400)
        review.is_approved = True
        review.save()
        return Response({"detail": "Review approved successfully."}, status=200)

    @swagger_auto_schema(
        method='post',
        operation_description="Reject a pending review (Admin only)",
        responses={
            200: "Review rejected and deleted",
            400: "Approved review cannot be rejected directly",
            404: "Review not found"
        }
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        review = self.get_object()
        if not review:
            return Response({"detail": "Review not found."}, status=404)
        if not review.is_approved:
            review.delete()
            return Response({"detail": "Review rejected and deleted."}, status=200)
        return Response({"detail": "Approved review cannot be rejected directly."}, status=400)


class ContactMessageViewSet(viewsets.ModelViewSet):
    queryset = ContactMessage.objects.all().order_by('-created_at')
    serializer_class = ContactMessageSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [AllowAny()]
        return [IsAdminUser()]

    @swagger_auto_schema(
        request_body=ContactMessageSerializer,
        responses={
            201: "Message submitted successfully.",
            400: "Validation error"
        }
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            instance = serializer.save()

            subject = f"New Contact Message from {instance.first_name}"
            message = (
                f"You have received a new contact message via the website:\n\n"
                f"Name:- {instance.first_name}\n"
                f"Email:- {instance.email}\n"
                f"Phone:- {instance.phone}\n"
                f"Submitted At:- {instance.created_at.strftime('%d-%b-%Y %I:%M %p')}\n\n"
                f"Message:-\n{instance.description}\n\n---\n"
            )

            # Background email sending to prevent timeout
            def send_email():
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, ['admin@a1ajinkya.com'])
                except Exception as e:
                    print("Email failed:", e)

            threading.Thread(target=send_email).start()

            return Response({"detail": "Message submitted successfully."}, status=201)
        return Response(serializer.errors, status=400)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"detail": "Message deleted successfully."}, status=200)


@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('status', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False)
    ],
    operation_description="Admin: Get full hostel booking history and student profile by student ID",
    responses={200: "Student profile + bookings", 404: "Student not found"}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def hostel_booking_history_by_student(request, student_id):
    if request.user.role != 'admin':
        return Response({'error': 'Only admin allowed'}, status=403)

    from users.models import User
    from users.serializers import UserSerializer

    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=404)

    status_filter = request.query_params.get('status')
    bookings = HostelBooking.objects.filter(student=student).order_by('-created_at')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    student_data = UserSerializer(student, context={'request': request}).data
    booking_data = HostelBookingSerializer(bookings, many=True, context={'request': request}).data

    return Response({
        "student": student_data,
        "bookings": booking_data
    })


@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('status', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False)
    ],
    operation_description="Admin: Get full library booking history and student profile by student ID",
    responses={200: "Student profile + bookings", 404: "Student not found"}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def library_booking_history_by_student(request, student_id):
    if request.user.role != 'admin':
        return Response({'error': 'Only admin allowed'}, status=403)

    from users.models import User
    from users.serializers import UserSerializer

    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=404)

    status_filter = request.query_params.get('status')
    bookings = LibraryBooking.objects.filter(student=student).order_by('-created_at')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    student_data = UserSerializer(student, context={'request': request}).data
    booking_data = LibraryBookingSerializer(bookings, many=True, context={'request': request}).data

    return Response({
        "student": student_data,
        "bookings": booking_data
    })


@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('student_id', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True),
        openapi.Parameter('status', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False)
    ],
    operation_description="Export hostel booking history for a student as CSV (admin only)"
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_hostel_bookings_csv_by_student(request):
    import csv
    from django.http import HttpResponse
    from users.models import User

    if request.user.role != 'admin':
        return Response({'error': 'Only admin allowed'}, status=403)

    student_id = request.query_params.get('student_id')
    status_filter = request.query_params.get('status')

    if not student_id:
        return Response({'error': 'student_id is required'}, status=400)

    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=404)

    bookings = HostelBooking.objects.filter(student=student)
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="hostel_bookings_{student.username}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Booking ID', 'Start Date', 'Status', 'Bed', 'Room', 'Remarks'])

    for b in bookings:
        writer.writerow([
            b.id,
            b.start_date,
            b.status,
            b.bed.bed_number if b.bed else '',
            b.bed.room.room_number if b.bed and b.bed.room else '',
            b.remarks or ''
        ])

    return response


@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('student_id', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True),
        openapi.Parameter('status', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False)
    ],
    operation_description="Export library booking history for a student as CSV (admin only)"
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_library_bookings_csv_by_student(request):
    import csv
    from django.http import HttpResponse
    from users.models import User

    if request.user.role != 'admin':
        return Response({'error': 'Only admin allowed'}, status=403)

    student_id = request.query_params.get('student_id')
    status_filter = request.query_params.get('status')

    if not student_id:
        return Response({'error': 'student_id is required'}, status=400)

    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=404)

    bookings = LibraryBooking.objects.filter(student=student)
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="library_bookings_{student.username}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Booking ID', 'Start Date', 'Status', 'Seat', 'Remarks'])

    for b in bookings:
        writer.writerow([
            b.id,
            b.start_date,
            b.status,
            b.seat.seat_number if b.seat else '',
            b.remarks or ''
        ])

    return response


@api_view(['GET'])
@permission_classes([IsAdminUser])
def student_full_profile(request, student_id):
    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=404)

    profile = {
        "id": student.id,
        "username": student.username,
        "first_name": student.first_name,
        "middle_name": student.middle_name,
        "last_name": student.last_name,
        "email": student.email,
        "phone_number": student.phone_number,
        "address": student.address,
        "education": student.education,
        "role": student.role,
        "profile_photo": request.build_absolute_uri(student.profile_photo.url) if student.profile_photo else None,
    }

    hostel_bookings = AdminHostelBookingSerializer(
        HostelBooking.objects.filter(student=student), many=True
    ).data

    library_bookings = AdminLibraryBookingSerializer(
        LibraryBooking.objects.filter(student=student), many=True
    ).data

    complaints = ComplaintSerializer(
        Complaint.objects.filter(submitted_by=student), many=True
    ).data
    reviews = ReviewSerializer(
        Review.objects.filter(name=student.username), many=True
    ).data

    return Response({
        "profile": profile,
        "hostel_bookings": hostel_bookings,
        "library_bookings": library_bookings,
        "complaints": complaints,
        "reviews": reviews
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def download_student_profile_pdf(request, student_id):
    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=404)

    hostel_bookings = HostelBooking.objects.filter(student=student)
    library_bookings = LibraryBooking.objects.filter(student=student)
    complaints = Complaint.objects.filter(submitted_by=student)
    reviews = Review.objects.filter(name=student.username)

    pdf_buffer = generate_student_profile_pdf(student, hostel_bookings, library_bookings, complaints, reviews)

    return HttpResponse(pdf_buffer, content_type='application/pdf')


@swagger_auto_schema(
    method='post',
    request_body=AdminSendEmailSerializer,
    operation_description="Admin: Send email to students by booking type (hostel/library/both)",
    responses={200: "Email sent", 400: "Validation error or no emails"}
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def send_email_to_students(request):
    serializer = AdminSendEmailSerializer(data=request.data)
    if serializer.is_valid():
        subject = serializer.validated_data['subject']
        message = serializer.validated_data['message']
        send_to_all = serializer.validated_data.get('send_to_all', False)
        recipient_ids = serializer.validated_data.get('recipient_ids', [])
        target_group = serializer.validated_data.get('target_group', 'both')

        # Get students based on target group
        hostel_students = HostelBooking.objects.filter(
            status__in=['pending', 'approved']
        ).values_list('student_id', flat=True)

        library_students = LibraryBooking.objects.filter(
            status__in=['pending', 'approved']
        ).values_list('student_id', flat=True)

        if target_group == 'hostel':
            eligible_ids = set(hostel_students)
        elif target_group == 'library':
            eligible_ids = set(library_students)
        else:  # both
            eligible_ids = set(hostel_students).union(set(library_students))

        if send_to_all:
            students = User.objects.filter(id__in=eligible_ids)
        else:
            students = User.objects.filter(id__in=recipient_ids).filter(id__in=eligible_ids)

        email_list = [user.email for user in students if user.email]

        if not email_list:
            return Response({'error': 'No valid emails found for selected students.'}, status=400)

        try:
            # logo_url = "https://a1ajinkya.com/static/images/logo.png"
            logo_url = request.build_absolute_uri('/static/images/logo.png')

            # Format message before f-string to avoid f-string escape issue
            formatted_message = message.replace('\n', '<br>')

            html_message = f"""
                <div style="font-family: Arial, sans-serif; padding: 10px;">
                    <img src="{logo_url}" alt="Bussiness Track Hostel & Library" style="max-width: 200px; margin-bottom: 20px;" />
                    <p>{formatted_message}</p>
                    <br>
                    <p>Thanks & Regards,<br>
                    Admin,<br>
                    <strong>Bussiness Track Hostel & Library</strong></p>
                </div>
            """

            email = EmailMessage(
                subject=subject,
                body=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=email_list
            )
            email.content_subtype = "html"
            email.send()

            return Response({'message': f'Email sent to {len(email_list)} student(s) successfully.'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    return Response(serializer.errors, status=400)


class AchievementBlogViewSet(viewsets.ModelViewSet):
    queryset = AchievementBlog.objects.all().order_by('-created_at')
    serializer_class = AchievementBlogSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'destroy']:
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def perform_create(self, serializer):
        serializer.save(posted_by=self.request.user)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data = {
            "message": "Achievement blog created successfully.",
            "blog": response.data
        }
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        response.data = {
            "message": "Achievement blog updated successfully.",
            "blog": response.data
        }
        return response

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"message": "Achievement blog deleted successfully."}, status=status.HTTP_200_OK)
