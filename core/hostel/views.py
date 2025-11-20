from django.utils import timezone
from rest_framework import viewsets, permissions, status, generics, filters, serializers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend
from django.http import HttpResponse
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from datetime import date, timedelta
import csv
from rest_framework.exceptions import PermissionDenied
from .models import HostelRoom, HostelBed, HostelBooking, HostelMonthlyFee, HostelMonthlyInvoice, \
    HostelAvailableSwitchRequest, HostelMutualSwitchRequest, HostelAvailableSwitchHistory, HostelMutualSwitchHistory
from .serializers import HostelRoomSerializer, HostelBedSerializer, HostelBookingSerializer, HostelMonthlyFeeSerializer, \
    HostelInvoiceAdminSerializer, HostelMonthlyInvoiceSerializer, HostelAvailableSwitchRequestSerializer, \
    HostelMutualSwitchRequestSerializer, HostelAvailableSwitchHistorySerializer, HostelMutualSwitchHistorySerializer
from core.utils.email_utils import send_rejection_email, send_approval_email, send_custom_email

from core.utils.sms_utils import send_sms
from core.utils.invoice_utils import generate_invoice_pdf
from rest_framework.permissions import IsAuthenticated
from core.utils.invoice_utils import generate_invoice_id
from rest_framework import filters
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from core.utils.invoice_utils import generate_hostel_invoice_pdf
from rest_framework.generics import ListAPIView
from .filters import HostelInvoiceFilter
from django.db import transaction
from django.db.models import Q


#  Custom role-based permissions
class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'admin'


class IsStudent(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'student'


#  Room ViewSet (admin only)
class HostelRoomViewSet(viewsets.ModelViewSet):
    queryset = HostelRoom.objects.all()
    serializer_class = HostelRoomSerializer
    permission_classes = [IsAdmin]

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if response.status_code == 201:
            response.data['detail'] = "Room created successfully."
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        if response.status_code == 200:
            response.data['detail'] = "Room updated successfully."
        return response

    def destroy(self, request, *args, **kwargs):
        room = self.get_object()
        from .models import HostelBooking
        active_beds = room.beds.filter(bookings__status__in=['approved', 'pending']).distinct()
        if active_beds.exists():
            return Response({"error": "Cannot delete. Room has booked or pending beds."}, status=400)

        response = super().destroy(request, *args, **kwargs)
        response.data = {"detail": "Room deleted successfully."}
        return response


#  Bed ViewSet (students view, admin manages)
class HostelBedViewSet(viewsets.ModelViewSet):
    queryset = HostelBed.objects.all()
    serializer_class = HostelBedSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['is_booked']

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'live_map']:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]

    @swagger_auto_schema(
        method='get',
        operation_description="Get all beds with current booking status",
        responses={200: "List of beds with booking info"}
    )
    @action(detail=False, methods=['get'], url_path='live-map', permission_classes=[permissions.AllowAny])
    def live_map(self, request):
        beds = HostelBed.objects.select_related('room').all()
        serializer = self.get_serializer(beds, many=True)
        base_data = serializer.data

        extended_data = []
        for bed, base in zip(beds, base_data):
            from hostel.models import HostelBooking, HostelMonthlyInvoice
            from datetime import date
            from calendar import monthrange

            latest_booking = (
                HostelBooking.objects
                .filter(bed=bed)
                .order_by('-created_at')
                .first()
            )

            status = "available"
            booking_id = None
            is_paid = False
            invoice_expired = True

            if latest_booking:
                if latest_booking.status == "pending":
                    status = "pending"
                    booking_id = latest_booking.id
                elif latest_booking.status == "approved":
                    status = "booked"
                    booking_id = latest_booking.id

                    latest_invoice = HostelMonthlyInvoice.objects.filter(booking=latest_booking).order_by(
                        '-month').first()
                    if latest_invoice:
                        today = date.today()
                        invoice_start = latest_invoice.month
                        year, month = invoice_start.year, invoice_start.month
                        last_day = monthrange(year, month)[1]
                        invoice_end = invoice_start.replace(day=last_day)

                        if today <= invoice_end:
                            is_paid = latest_invoice.is_paid
                            invoice_expired = not latest_invoice.is_paid
                        else:
                            is_paid = False
                            invoice_expired = True

            base['status'] = status
            base['booking_id'] = booking_id
            base['is_paid'] = is_paid
            base['invoice_expired'] = invoice_expired
            extended_data.append(base)

        return Response(extended_data)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if response.status_code == 201:
            response.data['detail'] = "Bed created successfully."
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        if response.status_code == 200:
            response.data['detail'] = "Bed updated successfully."
        return response

    def destroy(self, request, *args, **kwargs):
        bed = self.get_object()
        from .models import HostelBooking
        if HostelBooking.objects.filter(bed=bed, status__in=['approved', 'pending']).exists():
            return Response({"error": "Cannot delete. Bed is booked or has pending request."}, status=400)

        response = super().destroy(request, *args, **kwargs)
        response.data = {"detail": "Bed deleted successfully."}
        return response


#  Booking ViewSet (student books, admin approves/rejects)
class HostelBookingViewSet(viewsets.ModelViewSet):
    queryset = HostelBooking.objects.all()
    serializer_class = HostelBookingSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'bed__room__room_number']
    search_fields = ['student__first_name', 'student__last_name', 'student__username']

    @swagger_auto_schema(
        method='post',
        operation_description="Approve a pending hostel booking",
        responses={200: "Booking approved", 400: "Already processed"}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        import threading
        booking = self.get_object()

        if booking.status != 'pending':
            return Response({"detail": "Booking already processed."}, status=400)

        #  Approve current booking
        booking.status = 'approved'
        booking.approved_by = request.user
        booking.approved_at = timezone.now()
        booking.save()

        booking.bed.is_booked = True
        booking.bed.save()

        #  Notify approved student (email + sms)
        try:
            threading.Thread(target=send_approval_email, args=(
                booking.student.email,
                booking.student.username,
                "Hostel"
            )).start()

            if booking.student.phone_number:
                threading.Thread(target=send_sms, args=(
                    booking.student.phone_number,
                    f"Hi {booking.student.username}, your hostel booking has been approved."
                )).start()
        except Exception as e:
            print("Approval notification failed:", e)

        #  Reject & notify other pending bookings for same bed
        other_pending = HostelBooking.objects.filter(
            bed=booking.bed,
            status='pending'
        ).exclude(id=booking.id)

        for other in other_pending:
            try:
                threading.Thread(target=send_rejection_email, args=(
                    other.student.email,
                    other.student.username,
                    "Hostel"
                )).start()

                if other.student.phone_number:
                    threading.Thread(target=send_sms, args=(
                        other.student.phone_number,
                        f"Hi {other.student.username}, your hostel booking has been rejected."
                    )).start()

            except Exception as e:
                print("Rejection notification failed:", e)

            other.delete()

            #  WebSocket notify
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "live_seat_updates",
                {
                    "type": "send_seat_update",
                    "data": {
                        "type": "booking_rejected",
                        "bed_id": other.bed.id,
                        "room_id": other.bed.room.id,
                        "student": other.student.username,
                        "is_booked": False
                    }
                }
            )

        #  WebSocket approve broadcast
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "live_seat_updates",
            {
                "type": "send_seat_update",
                "data": {
                    "type": "booking_approved",
                    "bed_id": booking.bed.id,
                    "room_id": booking.bed.room.id,
                    "is_booked": True,
                    "student": booking.student.username
                }
            }
        )

        return Response({"detail": "Booking approved. Others rejected and notified."})

    @swagger_auto_schema(
        method='post',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'remarks': openapi.Schema(type=openapi.TYPE_STRING, description='Rejection reason (optional)')
            }
        ),
        operation_description="Reject a pending hostel booking",
        responses={200: "Booking rejected", 400: "Already processed"}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        import threading
        booking = self.get_object()

        if booking.status != 'pending':
            return Response({"detail": "Booking already processed."}, status=400)

        remarks = request.data.get("remarks", "").strip()
        if not remarks:
            remarks = "Rejected by admin."

        booking.status = 'rejected'
        booking.remarks = remarks
        booking.approved_at = timezone.now()
        booking.approved_by = request.user
        booking.save()

        #  Email Notification (Threaded)
        threading.Thread(target=send_rejection_email, args=(
            booking.student.email,
            booking.student.username,
            "Hostel"
        )).start()

        #  SMS Notification (Threaded)
        if booking.student.phone_number:
            threading.Thread(target=send_sms, args=(
                booking.student.phone_number,
                f"Hi {booking.student.username}, your hostel booking has been rejected."
            )).start()

        #  WebSocket update
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "live_seat_updates",
            {
                "type": "send_seat_update",
                "data": {
                    "type": "booking_rejected",
                    "bed_id": booking.bed.id,
                    "room_id": booking.bed.room.id,
                    "is_booked": False,
                    "rejected_by": booking.approved_by.username,
                    "student": booking.student.username,
                }
            }
        )

        return Response({"detail": "Booking rejected and student notified."})

    # def get_queryset(self):
    #     user = self.request.user
    #     if user.is_authenticated and user.role == 'admin':
    #         return HostelBooking.objects.all().order_by('-created_at')
    #     return HostelBooking.objects.filter(student=user).order_by('-created_at')

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return HostelBooking.objects.none()  # Prevents AnonymousUser error

        if user.is_authenticated and user.role == 'admin':
            return HostelBooking.objects.all().order_by('-created_at')

        return HostelBooking.objects.filter(student=user).order_by('-created_at')

    @swagger_auto_schema(
        method='get',
        operation_description="Export hostel bookings as CSV (Admin only)",
        responses={200: "CSV file"}
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAdmin])
    def export_csv(self, request):
        bookings = self.get_queryset()

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="hostel_bookings.csv"'

        writer = csv.writer(response)
        writer.writerow(['ID', 'Student', 'Status', 'Start Date', 'End Date', 'Approved By', 'Approved At', 'Remarks'])

        for b in bookings:
            writer.writerow([
                b.id,
                b.student.username,
                b.status,
                b.start_date,
                b.end_date,
                b.approved_by.username if b.approved_by else '',
                b.approved_at,
                b.remarks or ''
            ])

        return response

    @swagger_auto_schema(
        method='get',
        operation_description="Booking statistics for admin dashboard",
        responses={200: "Stats"}
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAdmin])
    def stats(self, request):
        data = {
            'total': HostelBooking.objects.filter(status='approved').count(),
            'approved': HostelBooking.objects.filter(status='approved').count(),
            'pending': HostelBooking.objects.filter(status='pending').count(),
            'rejected': HostelBooking.objects.filter(status='rejected').count(),
            'expired': HostelBooking.objects.filter(status='expired').count(),
        }
        return Response(data)

    @api_view(['GET'])
    @permission_classes([IsAdminUser])
    def hostel_dashboard_stats(request):
        from hostel.models import HostelBooking, HostelBed
        today = timezone.now().date()
        last_week = today - timedelta(days=7)

        total_beds = HostelBed.objects.count()
        booked_beds = HostelBed.objects.filter(is_booked=True).count()

        #  Pending = beds with booking (pending)
        pending_beds = HostelBooking.objects.filter(status='pending').values_list('bed_id',
                                                                                  flat=True).distinct().count()
        available_beds = total_beds - booked_beds - pending_beds

        today_bookings = HostelBooking.objects.filter(created_at__date=today).count()
        weekly_bookings = HostelBooking.objects.filter(created_at__date__gte=last_week).count()

        return Response({
            "hostel": {
                "total_beds": total_beds,
                "booked": booked_beds,
                "pending": pending_beds,
                "available": available_beds
            },
            "trends": {
                "today_bookings": today_bookings,
                "weekly_bookings": weekly_bookings
            }
        })

    @api_view(['GET'])
    @permission_classes([IsAdminUser])
    def export_hostel_bookings_csv(request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="hostel_bookings.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Username', 'First Name', 'Middle Name', 'Last Name',
            'Education',
            'Phone', 'Address',
            'Room', 'Bed',
            'Start Date',
            'Status'
        ])

        bookings = HostelBooking.objects.select_related('student', 'bed__room')
        for b in bookings:
            writer.writerow([
                b.student.username,
                b.student.first_name,
                b.student.middle_name,
                b.student.last_name,
                # b.student.aadhar_number,
                b.student.education,
                b.student.phone_number,
                b.student.address,
                b.bed.room.room_number,
                b.bed.bed_number,
                b.start_date,
                # b.end_date,
                b.status.upper()
            ])

        return response

    @swagger_auto_schema(
        method='post',
        operation_description="Cancel your own booking (Student) or any booking (Admin)",
        responses={200: "Booking cancelled", 400: "Only pending/approved bookings can be cancelled"}
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        user = request.user

        # Only allow cancel if status is pending or approved
        if booking.status not in ['pending', 'approved']:
            return Response({"detail": "Only pending or approved bookings can be cancelled."}, status=400)

        # Check if student is trying to cancel someone else's booking
        if user.role == 'student' and booking.student != user:
            raise PermissionDenied("You are not allowed to cancel this booking.")

        # Update booking status and free bed if already approved
        booking.status = 'cancelled'
        booking.remarks = 'Cancelled by ' + ('Admin' if user.role == 'admin' else 'Student')
        booking.end_date = timezone.now().date()
        booking.save()

        if booking.bed and booking.bed.is_booked:
            booking.bed.is_booked = False
            booking.bed.save()

        return Response({"detail": "Booking cancelled successfully."})

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request  # Pass request to serializer for profile photo fallback
        return context

    @swagger_auto_schema(
        method='get',
        operation_description="Get full student details for this hostel booking (Admin only)",
        responses={200: "Student detail response"}
    )
    @action(detail=True, methods=['get'], url_path='student-details', permission_classes=[IsAdminUser])
    def student_details(self, request, pk=None):
        try:
            booking = self.get_object()
            student = booking.student

            # Check Aadhaar from hostel booking
            aadhaar_front = booking.aadhaar_front_photo.url if booking.aadhaar_front_photo else None
            aadhaar_back = booking.aadhaar_back_photo.url if booking.aadhaar_back_photo else None

            # Fallback from library booking
            from library.models import LibraryBooking
            if not aadhaar_front or not aadhaar_back:
                library_booking = LibraryBooking.objects.filter(student=student,
                                                                status__in=['approved', 'pending']).last()
                if library_booking:
                    if not aadhaar_front and library_booking.aadhaar_front_photo:
                        aadhaar_front = library_booking.aadhaar_front_photo.url
                    if not aadhaar_back and library_booking.aadhaar_back_photo:
                        aadhaar_back = library_booking.aadhaar_back_photo.url

            return Response({
                "student": {
                    "id": student.id,
                    "username": student.username,
                    "full_name": f"{student.first_name} {student.middle_name} {student.last_name}".strip(),
                    "email": student.email,
                    "phone": student.phone_number,
                    "address": student.address,
                    "education": student.education,
                    "aadhaar_front": request.build_absolute_uri(aadhaar_front) if aadhaar_front else None,
                    "aadhaar_back": request.build_absolute_uri(aadhaar_back) if aadhaar_back else None,
                    "profile_photo": request.build_absolute_uri(
                        student.profile_photo.url) if student.profile_photo else None,
                    "purpose_of_joining": booking.purpose_of_joining,
                },

                "status": booking.status,
                "room": booking.bed.room.room_number if booking.bed else None,
                "bed": booking.bed.bed_number if booking.bed else None,
                "seat": None,
            })
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        method='get',
        operation_description="Get invoice for approved booking",
        responses={200: "PDF invoice", 400: "Only available for approved bookings"}
    )
    @action(detail=True, methods=['get'], url_path='invoice', permission_classes=[permissions.IsAuthenticated])
    def invoice(self, request, pk=None):
        booking = self.get_object()

        if booking.status != 'approved':
            return Response({"detail": "Invoice available only for approved bookings."}, status=400)

        student = booking.student
        summary = self.get_serializer(booking).data['billing_summary']

        pdf_buffer = generate_invoice_pdf(
            booking,
            student_name=f"{student.first_name} {student.last_name}",
            total_due=summary['total_due'],
            months=summary['months_active'],
            monthly_fee=summary['monthly_fee'],
            deposit=summary['deposit']
        )

        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=invoice_booking_{booking.id}.pdf'
        return response

    @swagger_auto_schema(
        method='get',
        operation_description="Check if student has previous hostel booking",
        responses={200: "Returns true/false"}
    )
    @action(detail=False, methods=['get'], url_path='has-previous', permission_classes=[permissions.IsAuthenticated])
    def has_previous(self, request):
        user = request.user
        exists = HostelBooking.objects.filter(student=user, status__in=['approved', 'cancelled', 'expired']).exists()
        return Response({'has_previous': exists})

    def create(self, request, *args, **kwargs):
        student = request.user
        existing = HostelBooking.objects.filter(
            student=student,
            status__in=['pending', 'approved']
        ).exists()

        if existing:
            return Response(
                {"error": "You already have an active or pending hostel booking."},
                status=400
            )

        response = super().create(request, *args, **kwargs)

        if response.status_code == 201:
            response.data['detail'] = " Hostel booking request submitted successfully."

        return response

    @swagger_auto_schema(
        method='get',
        manual_parameters=[
            openapi.Parameter(
                'bed_id',
                openapi.IN_QUERY,
                description="ID of the bed to fetch pending bookings",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ]
    )
    @action(detail=False, methods=['get'], url_path='pending-list', permission_classes=[IsAdmin])
    def pending_list(self, request):
        bed_id = request.query_params.get('bed_id')
        if not bed_id:
            return Response({"error": "bed_id is required"}, status=400)

        bookings = HostelBooking.objects.filter(bed_id=bed_id, status='pending').select_related('student')

        data = []
        for b in bookings:
            student = b.student
            data.append({
                "booking_id": b.id,
                "bed_id": b.bed.id,
                "student": {
                    "full_name": f"{student.first_name} {student.middle_name} {student.last_name}".strip(),
                    "email": student.email,
                    "phone": student.phone_number,
                    "education": student.education,
                    "address": student.address,
                    "aadhaar_front": request.build_absolute_uri(
                        b.aadhaar_front_photo.url) if b.aadhaar_front_photo else None,
                    "aadhaar_back": request.build_absolute_uri(
                        b.aadhaar_back_photo.url) if b.aadhaar_back_photo else None,
                    "profile_photo": request.build_absolute_uri(
                        student.profile_photo.url) if student.profile_photo else None,

                },
                "start_date": b.start_date,
                "purpose_of_joining": b.purpose_of_joining,
                "status": b.status,
                "created_at": b.created_at

            })

        return Response(data)


class HostelMonthlyFeeViewSet(viewsets.ModelViewSet):
    queryset = HostelMonthlyFee.objects.all().order_by('-effective_from')
    serializer_class = HostelMonthlyFeeSerializer
    permission_classes = [permissions.IsAdminUser]


@swagger_auto_schema(
    method='post',
    operation_description="Generate invoice for upcoming month (Student or Admin with student_id)",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'student_id': openapi.Schema(type=openapi.TYPE_INTEGER, description='Student ID (required only for admin)')
        },
        required=[]
    ),
    responses={
        200: "Invoice generated",
        400: "Conditions not met",
        500: "Fee settings missing"
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_hostel_invoice(request):
    from calendar import monthrange
    from datetime import date

    user = request.user
    student_id = request.data.get("student_id")
    if user.role == "admin" and student_id:
        from users.models import User
        try:
            user = User.objects.get(id=student_id, role="student")
        except User.DoesNotExist:
            return Response({"error": "Invalid student ID"}, status=400)

    try:
        booking = HostelBooking.objects.get(student=user, status="approved")
    except HostelBooking.DoesNotExist:
        return Response({"error": "No active hostel booking found."}, status=400)

    today = date.today()
    current_month = today.replace(day=1)
    is_first_invoice = not HostelMonthlyInvoice.objects.filter(booking=booking).exists()

    # Prevent duplicate
    if HostelMonthlyInvoice.objects.filter(booking=booking, month=current_month).exists():
        return Response({"error": "Invoice already generated for this month."}, status=400)

    # Prevent early generation
    if not is_first_invoice:
        last_invoice = HostelMonthlyInvoice.objects.filter(booking=booking).order_by('-month').first()
        year, month = last_invoice.month.year, last_invoice.month.month
        last_day = monthrange(year, month)[1]
        invoice_end_date = last_invoice.month.replace(day=last_day)

        days_left = (invoice_end_date - today).days
        if days_left > 2:
            return Response({
                "error": f"Next invoice can only be generated in last 3 days of current invoice cycle. {days_left} days remaining."
            }, status=400)

    # Fee Config
    fees = HostelMonthlyFee.objects.last()
    if not fees:
        return Response({"error": "Hostel fee settings not configured."}, status=500)

    # Set actual start date
    # invoice_start = booking.start_date if is_first_invoice else (last_invoice.month + timedelta(days=30))

    # Fee Slab
    if is_first_invoice:
        booking_day = booking.start_date.day
        if booking_day <= 10:
            monthly_fee = 1500
        elif booking_day <= 20:
            monthly_fee = 1000
        else:
            monthly_fee = 500
        deposit = fees.deposit_amount
    else:
        monthly_fee = fees.monthly_fee
        deposit = 0

    total = monthly_fee + deposit

    invoice = HostelMonthlyInvoice.objects.create(
        booking=booking,
        invoice_id=generate_invoice_id("HO", booking.id, current_month),
        month=current_month,
        amount=monthly_fee,
        deposit=deposit,
        total=total,
        invoice_expired=False
    )

    return Response(HostelMonthlyInvoiceSerializer(invoice).data)


@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('bed_id', openapi.IN_QUERY, description="Bed ID", type=openapi.TYPE_INTEGER)
    ],
    responses={200: 'Billing summary response'}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def hostel_billing_summary(request):
    bed_id = request.GET.get('bed_id')
    fee_config = HostelMonthlyFee.objects.last()
    if not bed_id or not fee_config:
        return Response({'error': 'Bed or fee config missing'}, status=400)

    today = timezone.now().date()
    day = today.day

    if day <= 10:
        monthly_fee = 1500
    elif day <= 20:
        monthly_fee = 1000
    else:
        monthly_fee = 500

    return Response({
        'monthly_fee': monthly_fee,
        'deposit_amount': fee_config.deposit_amount,
        'total': monthly_fee + fee_config.deposit_amount
    })


@swagger_auto_schema(
    method='get',
    operation_description="Student: Get current hostel booking status (active/inactive)",
    tags=["student-booking-status"],
    responses={200: openapi.Response(description="Booking status")}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_hostel_booking_status(request):
    user = request.user
    has_active = HostelBooking.objects.filter(student=user, status='approved').exists()
    return Response({"status": "active" if has_active else "inactive"})


@swagger_auto_schema(
    method='get',
    operation_description="Download hostel monthly invoice PDF by invoice ID",
    responses={200: "PDF invoice", 404: "Invoice not found"}
)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def download_hostel_invoice_pdf(request, invoice_id):
    try:
        invoice = HostelMonthlyInvoice.objects.get(id=invoice_id, booking__student=request.user)
    except HostelMonthlyInvoice.DoesNotExist:
        return Response({"detail": "Invoice not found."}, status=404)

    pdf_buffer = generate_hostel_invoice_pdf(invoice)
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=hostel_invoice_{invoice.invoice_id}.pdf'
    return response


class MyHostelInvoicesView(ListAPIView):
    serializer_class = HostelMonthlyInvoiceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = HostelInvoiceFilter

    def get_queryset(self):
        return HostelMonthlyInvoice.objects.filter(booking__student=self.request.user)


class AdminHostelInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HostelMonthlyInvoice.objects.select_related('booking__student', 'booking__bed__room').all()
    serializer_class = HostelInvoiceAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_paid']
    search_fields = ['booking__student__username', 'booking__student__first_name', 'booking__student__last_name']

    def get_queryset(self):
        queryset = super().get_queryset()
        student_id = self.request.query_params.get('student_id')
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')
        is_paid = self.request.query_params.get('is_paid')

        if student_id:
            queryset = queryset.filter(booking__student__id=student_id)
        if is_paid in ['true', 'false']:
            queryset = queryset.filter(is_paid=(is_paid.lower() == 'true'))
        if month and year:
            queryset = queryset.filter(month__month=month, month__year=year)

        return queryset


@swagger_auto_schema(
    method='post',
    operation_description="Mark a hostel invoice as paid (Admin only)",
    responses={200: "Marked as paid", 404: "Invoice not found"}
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def mark_hostel_invoice_paid(request, invoice_id):
    from .models import HostelMonthlyInvoice
    try:
        invoice = HostelMonthlyInvoice.objects.get(id=invoice_id)
        invoice.is_paid = True
        invoice.paid_on = timezone.now()
        invoice.save()
        return Response({"detail": "Invoice marked as paid."})
    except HostelMonthlyInvoice.DoesNotExist:
        return Response({"error": "Invoice not found."}, status=404)


@swagger_auto_schema(
    method='post',
    operation_description="Admin: Generate invoices for all approved hostel bookings for current month",
    responses={200: "Invoices generated", 400: "No eligible bookings", 500: "Error occurred"}
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def generate_hostel_invoices_bulk(request):
    from calendar import monthrange
    from datetime import date
    today = date.today()
    current_month = today.replace(day=1)

    from .models import HostelBooking, HostelMonthlyInvoice, HostelMonthlyFee
    from core.utils.invoice_utils import generate_invoice_id

    approved_bookings = HostelBooking.objects.filter(status='approved')
    fees = HostelMonthlyFee.objects.last()
    if not fees:
        return Response({"error": "Hostel fee settings not configured."}, status=500)

    count = 0
    for booking in approved_bookings:
        if HostelMonthlyInvoice.objects.filter(booking=booking, month=current_month).exists():
            continue

        is_first_invoice = not HostelMonthlyInvoice.objects.filter(booking=booking).exists()

        if is_first_invoice:
            booking_day = booking.start_date.day
            if booking_day <= 10:
                monthly_fee = 1500
            elif booking_day <= 20:
                monthly_fee = 1000
            else:
                monthly_fee = 500
            deposit = fees.deposit_amount
        else:
            monthly_fee = fees.monthly_fee
            deposit = 0

        total = monthly_fee + deposit

        HostelMonthlyInvoice.objects.create(
            booking=booking,
            invoice_id=generate_invoice_id("HO", booking.id, current_month),
            month=current_month,
            amount=monthly_fee,
            deposit=deposit,
            total=total,
            invoice_expired=False
        )
        count += 1

    return Response({"message": f"{count} hostel invoices generated."})


# ========= SWITCH VIEWS (HOSTEL) =========


class HostelAvailableSwitchRequestViewSet(viewsets.ModelViewSet):
    queryset = HostelAvailableSwitchRequest.objects.select_related('booking__student', 'booking__bed__room',
                                                                   'target_bed__room')
    serializer_class = HostelAvailableSwitchRequestSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    def get_permissions(self):
        if self.action in ['create', 'list', 'retrieve', 'cancel']:
            return [permissions.IsAuthenticated()]
        # approve/reject admin only
        return [IsAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.is_authenticated and getattr(u, 'role', None) == 'admin':
            return qs.order_by('-created_at')
        return qs.filter(booking__student=u).order_by('-created_at')

    # CREATE => POST /api/hostel/switch-requests/available/  { "target_bed": <id> }
    def create(self, request, *args, **kwargs):
        # request.user must be student; serializer validates rest
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(method='post', operation_description="Approve available switch (Admin)",
                         responses={200: "Approved"})
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        sr = self.get_object()
        if sr.status != 'pending':
            return Response({"error": "Already processed."}, status=400)

        booking = sr.booking
        from_bed = booking.bed
        to_bed = sr.target_bed

        # Re-validate availability
        if to_bed.is_booked:
            return Response({"error": "Target bed is no longer available."}, status=400)
        if booking.status != 'approved':
            return Response({"error": "Booking is not approved."}, status=400)

        # Do the move
        if from_bed and from_bed.id == to_bed.id:
            return Response({"error": "Same bed. Nothing to switch."}, status=400)

        # free old, occupy new
        if from_bed:
            from_bed.is_booked = False
            from_bed.save()
        booking.bed = to_bed
        booking.save()
        to_bed.is_booked = True
        to_bed.save()

        sr.status = 'approved'
        sr.approved_by = request.user
        sr.approved_at = timezone.now()
        sr.save()

        HostelAvailableSwitchHistory.objects.create(
            booking=booking, from_bed=from_bed, to_bed=to_bed,
            action='approved', actor=request.user, remarks=sr.remarks or ''
        )

        # Notify student
        try:
            send_custom_email(
                to_email=booking.student.email,
                subject="Hostel Switch Approved",
                message=f"Your bed has been switched to {to_bed.room.room_number} - {to_bed.bed_number}."
            )
        except Exception as e:
            print("Email failed:", e)

        return Response({"detail": "Switch approved and bed moved."})

    @swagger_auto_schema(method='post', operation_description="Reject available switch (Admin)",
                         request_body=openapi.Schema(type=openapi.TYPE_OBJECT, properties={
                             'remarks': openapi.Schema(type=openapi.TYPE_STRING)
                         }))
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        sr = self.get_object()
        if sr.status != 'pending':
            return Response({"error": "Already processed."}, status=400)
        sr.status = 'rejected'
        sr.remarks = (request.data.get('remarks') or '').strip() or 'Rejected by admin'
        sr.approved_by = request.user
        sr.approved_at = timezone.now()
        sr.save()

        HostelAvailableSwitchHistory.objects.create(
            booking=sr.booking, from_bed=sr.booking.bed, to_bed=sr.target_bed,
            action='rejected', actor=request.user, remarks=sr.remarks
        )

        try:
            send_custom_email(
                to_email=sr.booking.student.email,
                subject="Hostel Switch Rejected",
                message=f"Your switch request has been rejected. Remarks: {sr.remarks}"
            )
        except Exception as e:
            print("Email failed:", e)

        return Response({"detail": "Request rejected."})

    @swagger_auto_schema(method='post', operation_description="Cancel own available switch (Student)",
                         request_body=openapi.Schema(type=openapi.TYPE_OBJECT, properties={
                             'remarks': openapi.Schema(type=openapi.TYPE_STRING)
                         }))
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        sr = self.get_object()
        if sr.status != 'pending':
            return Response({"error": "Only pending requests can be cancelled."}, status=400)
        # Only owner student OR admin
        if request.user.role != 'admin' and sr.booking.student != request.user:
            raise PermissionDenied("Not allowed.")

        sr.status = 'cancelled'
        sr.remarks = (request.data.get('remarks') or '').strip() or 'Cancelled by student'
        sr.save()

        HostelAvailableSwitchHistory.objects.create(
            booking=sr.booking, from_bed=sr.booking.bed, to_bed=sr.target_bed,
            action='cancelled', actor=request.user, remarks=sr.remarks
        )
        return Response({"detail": "Request cancelled."})


class HostelMutualSwitchRequestViewSet(viewsets.ModelViewSet):
    queryset = HostelMutualSwitchRequest.objects.select_related(
        'requester_booking__student', 'requester_booking__bed__room',
        'partner_booking__student', 'partner_booking__bed__room'
    )
    serializer_class = HostelMutualSwitchRequestSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    def get_permissions(self):
        if self.action in ['create', 'list', 'retrieve', 'cancel']:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.is_authenticated and getattr(u, 'role', None) == 'admin':
            return qs.order_by('-created_at')
        return qs.filter(requester_booking__student=u).order_by('-created_at')

    # CREATE => POST /api/hostel/switch-requests/mutual/ { "mutual_booking_id": int (optional) }
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(method='post', operation_description="Reject mutual switch (Admin)",
                         request_body=openapi.Schema(type=openapi.TYPE_OBJECT, properties={
                             'remarks': openapi.Schema(type=openapi.TYPE_STRING)
                         }))
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        mr = self.get_object()
        if mr.status != 'pending':
            return Response({"error": "Already processed."}, status=400)
        mr.status = 'rejected'
        mr.remarks = (request.data.get('remarks') or '').strip() or 'Rejected by admin'
        mr.approved_by = request.user
        mr.approved_at = timezone.now()
        mr.save()

        HostelMutualSwitchHistory.objects.create(
            booking_a=mr.requester_booking, booking_b=mr.partner_booking,
            from_bed_a=mr.requester_booking.bed, to_bed_a=mr.partner_booking.bed if mr.partner_booking else None,
            from_bed_b=mr.partner_booking.bed if mr.partner_booking else None, to_bed_b=mr.requester_booking.bed,
            action='rejected', actor=request.user, remarks=mr.remarks
        )

        try:
            send_custom_email(
                to_email=mr.requester_booking.student.email,
                subject="Hostel Mutual Switch Rejected",
                message=f"Your mutual switch was rejected. Remarks: {mr.remarks}"
            )
        except Exception as e:
            print("Email failed:", e)

        return Response({"detail": "Request rejected."})

    @swagger_auto_schema(method='post', operation_description="Cancel own mutual switch (Student)",
                         request_body=openapi.Schema(type=openapi.TYPE_OBJECT, properties={
                             'remarks': openapi.Schema(type=openapi.TYPE_STRING)
                         }))
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        mr = self.get_object()
        if mr.status != 'pending':
            return Response({"error": "Only pending requests can be cancelled."}, status=400)
        if request.user.role != 'admin' and mr.requester_booking.student != request.user:
            raise PermissionDenied("Not allowed.")
        mr.status = 'cancelled'
        mr.remarks = (request.data.get('remarks') or '').strip() or 'Cancelled by student'
        mr.save()

        HostelMutualSwitchHistory.objects.create(
            booking_a=mr.requester_booking, booking_b=mr.partner_booking,
            from_bed_a=mr.requester_booking.bed, to_bed_a=mr.partner_booking.bed if mr.partner_booking else None,
            from_bed_b=mr.partner_booking.bed if mr.partner_booking else None, to_bed_b=mr.requester_booking.bed,
            action='cancelled', actor=request.user, remarks=mr.remarks
        )
        return Response({"detail": "Request cancelled."})

    @swagger_auto_schema(
        method='post',
        operation_description="Admin: Match two OPEN/targeted mutual requests and approve swap",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['request_a_id', 'request_b_id'],
            properties={
                'request_a_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                'request_b_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                'remarks': openapi.Schema(type=openapi.TYPE_STRING),
            }
        ),
        responses={200: "Swapped"}
    )
    @action(detail=False, methods=['post'], url_path='match-and-approve')
    @transaction.atomic
    def match_and_approve(self, request):
        a_id = request.data.get('request_a_id')
        b_id = request.data.get('request_b_id')
        remarks = (request.data.get('remarks') or '').strip()

        try:
            a = HostelMutualSwitchRequest.objects.select_for_update().get(id=a_id, status='pending')
            b = HostelMutualSwitchRequest.objects.select_for_update().get(id=b_id, status='pending')
        except HostelMutualSwitchRequest.DoesNotExist:
            return Response({"error": "Both requests must be pending."}, status=400)

        if a.requester_booking_id == b.requester_booking_id:
            return Response({"error": "Requests must be from two different bookings."}, status=400)

        ba = a.requester_booking
        bb = b.requester_booking

        if ba.status != 'approved' or bb.status != 'approved':
            return Response({"error": "Both bookings must be approved."}, status=400)

        bed_a = ba.bed
        bed_b = bb.bed
        if not bed_a or not bed_b:
            return Response({"error": "Both bookings must have valid beds."}, status=400)
        if bed_a.id == bed_b.id:
            # no-op, but mark approved to close loop
            pass

        # swap
        ba.bed = bed_b
        bb.bed = bed_a
        ba.save();
        bb.save()

        # beds remain booked=True, no change

        for mr in (a, b):
            mr.status = 'approved'
            mr.approved_by = request.user
            mr.approved_at = timezone.now()
            mr.remarks = remarks or mr.remarks
            mr.save()

        HostelMutualSwitchHistory.objects.create(
            booking_a=ba, booking_b=bb,
            from_bed_a=bed_a, to_bed_a=ba.bed,
            from_bed_b=bed_b, to_bed_b=bb.bed,
            action='approved', actor=request.user, remarks=remarks
        )

        # Notify both
        for bk in (ba, bb):
            try:
                send_custom_email(
                    to_email=bk.student.email,
                    subject="Hostel Mutual Switch Approved",
                    message=f"Your bed has been switched to {bk.bed.room.room_number} - {bk.bed.bed_number}."
                )
            except Exception as e:
                print("Email failed:", e)

        return Response({"detail": "Mutual swap approved and beds swapped."})


# ===== HISTORY VIEWS (HOSTEL) =====

class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, 'role', '') == 'admin'


class HostelAvailableSwitchHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HostelAvailableSwitchHistory.objects.select_related(
        'booking__student', 'from_bed__room', 'to_bed__room'
    ).order_by('-created_at')
    serializer_class = HostelAvailableSwitchHistorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['action']  # approved/rejected/cancelled

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if getattr(u, 'role', '') == 'admin':
            return qs
        # student: only own booking history
        return qs.filter(booking__student=u)


class HostelMutualSwitchHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HostelMutualSwitchHistory.objects.select_related(
        'booking_a__student', 'booking_b__student'
    ).order_by('-created_at')
    serializer_class = HostelMutualSwitchHistorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['action']

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if getattr(u, 'role', '') == 'admin':
            return qs
        # show records where the student was A or B
        # return qs.filter(models.Q(booking_a__student=u) | models.Q(booking_b__student=u))

        return qs.filter(Q(booking_a__student=u) | Q(booking_b__student=u))

