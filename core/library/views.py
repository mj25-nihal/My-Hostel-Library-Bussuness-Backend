from django.utils import timezone
from rest_framework import viewsets, permissions, status, generics, serializers
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend
from django.http import HttpResponse
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import csv
from rest_framework.exceptions import PermissionDenied
from .models import LibrarySeat, TimeSlot, LibraryBooking, LibraryMonthlyFee, LibraryMonthlyInvoice, LibraryFeeSetting, \
    LibraryAvailableSwitchRequest, LibraryMutualSwitchRequest, LibraryAvailableSwitchHistory, LibraryMutualSwitchHistory
from .serializers import LibrarySeatSerializer, TimeSlotSerializer, LibraryBookingSerializer, \
    LibraryMonthlyFeeSerializer, LibraryInvoiceAdminSerializer, LibraryAvailableSwitchRequestSerializer, \
    LibraryMutualSwitchRequestSerializer, LibraryAvailableSwitchHistorySerializer, LibraryMutualSwitchHistorySerializer
from hostel.views import IsAdmin, IsStudent
from core.utils.email_utils import send_rejection_email, send_approval_email, send_custom_email
from core.utils.sms_utils import send_sms
from core.utils.invoice_utils import generate_invoice_pdf
from rest_framework.permissions import IsAuthenticated
from core.utils.invoice_utils import generate_invoice_id
from .serializers import LibraryMonthlyInvoiceSerializer
from rest_framework import filters
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from hostel.models import HostelBooking
from library.models import LibraryBooking, LibraryMonthlyInvoice
from core.utils.invoice_utils import generate_library_invoice_pdf
from rest_framework.generics import ListAPIView
from .filters import LibraryInvoiceFilter
from django.db import transaction
from django.db.models import Q


class LibrarySeatViewSet(viewsets.ModelViewSet):
    queryset = LibrarySeat.objects.all()
    serializer_class = LibrarySeatSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['is_booked']

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'live_map']:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]

    @swagger_auto_schema(
        method='get',
        operation_description="Get all library seats with current booking status",
        responses={200: "List of seats with status"}
    )
    @action(detail=False, methods=['get'], url_path='live-map', permission_classes=[permissions.AllowAny])
    def live_map(self, request):
        seats = LibrarySeat.objects.all()
        serializer = self.get_serializer(seats, many=True)
        base_data = serializer.data

        extended_data = []
        for seat, base in zip(seats, base_data):
            from library.models import LibraryBooking, LibraryMonthlyInvoice
            from datetime import date
            from calendar import monthrange

            latest_booking = (
                LibraryBooking.objects
                .filter(seat=seat)
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

                    latest_invoice = LibraryMonthlyInvoice.objects.filter(booking=latest_booking).order_by(
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
            response.data['detail'] = "Seat created successfully."
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        if response.status_code == 200:
            response.data['detail'] = "Seat updated successfully."
        return response

    def destroy(self, request, *args, **kwargs):
        seat = self.get_object()
        from .models import LibraryBooking
        if LibraryBooking.objects.filter(seat=seat, status__in=['approved', 'pending']).exists():
            return Response({"error": "Cannot delete. Seat is booked or has pending request."}, status=400)

        response = super().destroy(request, *args, **kwargs)
        response.data = {"detail": "Seat deleted successfully."}
        return response


class TimeSlotViewSet(viewsets.ModelViewSet):
    queryset = TimeSlot.objects.all()
    serializer_class = TimeSlotSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]


class LibraryBookingViewSet(viewsets.ModelViewSet):
    queryset = LibraryBooking.objects.all()
    serializer_class = LibraryBookingSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'seat__seat_number']
    search_fields = ['student__first_name', 'student__last_name', 'student__username']

    @swagger_auto_schema(
        method='post',
        operation_description="Approve a pending library booking (Admin only)",
        responses={200: "Booking approved", 400: "Already processed"}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def approve(self, request, pk=None):
        import threading
        booking = self.get_object()

        if booking.status != 'pending':
            return Response({"detail": "Booking already processed."}, status=400)

        # Approve this booking
        booking.status = 'approved'
        booking.approved_by = request.user
        booking.approved_at = timezone.now()
        booking.save()

        booking.seat.is_booked = True
        booking.seat.save()

        # Notify approved student (Email + SMS in thread)
        try:
            threading.Thread(target=send_approval_email, args=(
                booking.student.email,
                booking.student.username,
                "Library"
            )).start()

            if booking.student.phone_number:
                threading.Thread(target=send_sms, args=(
                    booking.student.phone_number,
                    f"Hi {booking.student.username}, your library booking has been approved."
                )).start()
        except Exception as e:
            print("Approve notification failed:", e)

        # Reject all other pending bookings for this seat
        other_pending = LibraryBooking.objects.filter(
            seat=booking.seat,
            status='pending'
        ).exclude(id=booking.id)

        for other in other_pending:
            try:
                threading.Thread(target=send_rejection_email, args=(
                    other.student.email,
                    other.student.username,
                    "Library"
                )).start()

                if other.student.phone_number:
                    threading.Thread(target=send_sms, args=(
                        other.student.phone_number,
                        f"Hi {other.student.username}, your library booking has been rejected."
                    )).start()

            except Exception as e:
                print("Rejection notification failed:", e)

            other.delete()

            # WebSocket notify for rejection
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "live_seat_updates",
                {
                    "type": "send_seat_update",
                    "data": {
                        "type": "library_booking_rejected",
                        "seat_id": other.seat.id,
                        "is_booked": False,
                        "student": other.student.username
                    }
                }
            )

        # WebSocket notify for approval
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "live_seat_updates",
            {
                "type": "send_seat_update",
                "data": {
                    "type": "library_booking_approved",
                    "seat_id": booking.seat.id,
                    "is_booked": True,
                    "student": booking.student.username
                }
            }
        )

        return Response({"detail": "Library booking approved. Others rejected and notified."})

    @swagger_auto_schema(
        method='post',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'remarks': openapi.Schema(type=openapi.TYPE_STRING, description='Rejection remarks (optional)')
            }
        ),
        operation_description="Reject a pending library booking (Admin only)",
        responses={200: "Booking rejected", 400: "Already processed"}
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
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

        # Mark seat as unbooked (safe)
        booking.seat.is_booked = False
        booking.seat.save()

        # Notify student via Email + SMS (threaded)
        threading.Thread(target=send_rejection_email, args=(
            booking.student.email,
            booking.student.username,
            "Library"
        )).start()

        if booking.student.phone_number:
            threading.Thread(target=send_sms, args=(
                booking.student.phone_number,
                f"Hi {booking.student.username}, your library booking has been rejected."
            )).start()

        # WebSocket notify
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "live_seat_updates",
            {
                "type": "send_seat_update",
                "data": {
                    "type": "library_booking_rejected",
                    "seat_id": booking.seat.id,
                    "is_booked": False,
                    "student": booking.student.username
                }
            }
        )

        return Response({
            "detail": "Library booking rejected and student notified."
        })

    # def get_queryset(self):
    #     user = self.request.user
    #     if user.is_authenticated and user.role == 'admin':
    #         return LibraryBooking.objects.all().order_by('-created_at')
    #     return LibraryBooking.objects.filter(student=user).order_by('-created_at')

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return LibraryBooking.objects.none()  # Or raise PermissionDenied

        if user.role == 'admin':
            return LibraryBooking.objects.all().order_by('-created_at')

        return LibraryBooking.objects.filter(student=user).order_by('-created_at')

    @swagger_auto_schema(
        method='get',
        operation_description="Library booking stats for dashboard",
        responses={200: "Stats data"}
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAdmin])
    def stats(self, request):
        data = {
            'total': LibraryBooking.objects.filter(status='approved').count(),
            'approved': LibraryBooking.objects.filter(status='approved').count(),
            'pending': LibraryBooking.objects.filter(status='pending').count(),
            'rejected': LibraryBooking.objects.filter(status='rejected').count(),
            'expired': LibraryBooking.objects.filter(status='expired').count(),
        }
        return Response(data)

    @swagger_auto_schema(
        operation_description="Export library bookings to CSV",
        responses={200: "CSV file"}
    )
    def export_csv(self, request):
        bookings = self.get_queryset()

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="library_bookings.csv"'

        writer = csv.writer(response)
        writer.writerow(
            ['ID', 'Student', 'Seat', 'Status', 'Start Date', 'End Date', 'Approved By', 'Approved At', 'Remarks'])

        for b in bookings:
            writer.writerow([
                b.id,
                b.student.username,
                b.seat.seat_number,
                b.status,
                b.start_date,
                b.end_date,
                b.approved_by.username if b.approved_by else '',
                b.approved_at,
                b.remarks or ''
            ])

        return response

    @api_view(['GET'])
    @permission_classes([IsAdminUser])
    def library_dashboard_stats(request):
        today = timezone.now().date()
        last_week = today - timedelta(days=7)

        total_seats = LibrarySeat.objects.count()
        booked_seats = LibrarySeat.objects.filter(is_booked=True).count()

        pending_seats = LibraryBooking.objects.filter(status='pending').values_list('seat_id',
                                                                                    flat=True).distinct().count()
        available_seats = total_seats - booked_seats - pending_seats

        today_bookings = LibraryBooking.objects.filter(created_at__date=today).count()
        weekly_bookings = LibraryBooking.objects.filter(created_at__date__gte=last_week).count()

        return Response({
            "library": {
                "total_seats": total_seats,
                "booked": booked_seats,
                "pending": pending_seats,
                "available": available_seats
            },
            "trends": {
                "today_bookings": today_bookings,
                "weekly_bookings": weekly_bookings
            }
        })

    @api_view(['GET'])
    @permission_classes([IsAdminUser])
    def export_library_bookings_csv(request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="library_bookings.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Username', 'First Name', 'Middle Name', 'Last Name',
            'Education',
            'Phone', 'Address',
            'Seat Number',
            'Start Date',
            'Status'
        ])

        bookings = LibraryBooking.objects.select_related('student', 'seat')
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
                b.seat.seat_number,
                b.start_date,
                # b.end_date,
                b.status.upper()
            ])

        return response

    @swagger_auto_schema(
        method='post',
        operation_description="Cancel own booking (Student) or any booking (Admin)",
        responses={200: "Booking cancelled", 400: "Invalid status"}
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        user = request.user

        #  Only pending/approved bookings can be cancelled
        if booking.status not in ['pending', 'approved']:
            return Response({"detail": "Only pending or approved bookings can be cancelled."}, status=400)

        #  Student can cancel only their own booking
        if user.role == 'student' and booking.student != user:
            raise PermissionDenied("You are not allowed to cancel this booking.")

        #  Cancel it and unbook seat if needed
        booking.status = 'cancelled'
        booking.remarks = 'Cancelled by ' + ('Admin' if user.role == 'admin' else 'Student')
        booking.end_date = timezone.now().date()

        booking.save()

        if booking.seat and booking.seat.is_booked:
            booking.seat.is_booked = False
            booking.seat.save()

        return Response({"detail": "Booking cancelled successfully."})

    @action(detail=True, methods=['get'], url_path='student-details', permission_classes=[IsAdminUser])
    def student_details(self, request, pk=None):
        try:
            booking = self.get_object()
            student = booking.student

            # Check Aadhaar from library booking
            aadhaar_front = booking.aadhaar_front_photo.url if booking.aadhaar_front_photo else None
            aadhaar_back = booking.aadhaar_back_photo.url if booking.aadhaar_back_photo else None

            #  Fallback from hostel booking
            from hostel.models import HostelBooking
            if not aadhaar_front or not aadhaar_back:
                hostel_booking = HostelBooking.objects.filter(student=student,
                                                              status__in=['approved', 'pending']).last()
                if hostel_booking:
                    if not aadhaar_front and hostel_booking.aadhaar_front_photo:
                        aadhaar_front = hostel_booking.aadhaar_front_photo.url
                    if not aadhaar_back and hostel_booking.aadhaar_back_photo:
                        aadhaar_back = hostel_booking.aadhaar_back_photo.url

            return Response({
                "student": {
                    "id": student.id,
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
                "seat": booking.seat.seat_number if booking.seat else None,
                "room": None,
                "bed": None
            })
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        method='get',
        operation_description="Get invoice for approved library booking",
        responses={200: "PDF Invoice", 400: "Only for approved bookings"}
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
        response['Content-Disposition'] = f'attachment; filename=invoice_library_{booking.id}.pdf'
        return response

    @swagger_auto_schema(
        method='get',
        operation_description="Check if student has previous library booking",
        responses={200: openapi.Response("True/False")}
    )
    @action(detail=False, methods=['get'], url_path='has-previous', permission_classes=[permissions.IsAuthenticated])
    def has_previous(self, request):
        user = request.user
        exists = LibraryBooking.objects.filter(student=user, status__in=['approved', 'cancelled', 'expired']).exists()
        return Response({'has_previous': exists})

    def create(self, request, *args, **kwargs):
        student = request.user
        existing = LibraryBooking.objects.filter(
            student=student,
            status__in=['pending', 'approved']
        ).exists()

        if existing:
            return Response(
                {"error": "You already have an active or pending library booking."},
                status=400
            )

        response = super().create(request, *args, **kwargs)

        if response.status_code == 201:
            response.data['detail'] = " Library booking request submitted successfully."

        return response

    @swagger_auto_schema(
        method='get',
        manual_parameters=[
            openapi.Parameter(
                'seat_id',
                openapi.IN_QUERY,
                description="ID of the seat to fetch pending bookings",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ]
    )
    @action(detail=False, methods=['get'], url_path='pending-list', permission_classes=[IsAdmin])
    def pending_list(self, request):
        seat_id = request.query_params.get('seat_id')
        if not seat_id:
            return Response({"error": "seat_id is required"}, status=400)

        bookings = LibraryBooking.objects.filter(seat_id=seat_id, status='pending').select_related('student')

        data = []
        for b in bookings:
            student = b.student
            data.append({
                "booking_id": b.id,
                "seat_id": b.seat.id,
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


class LibraryMonthlyFeeViewSet(viewsets.ModelViewSet):
    queryset = LibraryMonthlyFee.objects.all().order_by('-effective_from')
    serializer_class = LibraryMonthlyFeeSerializer
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
def generate_library_invoice(request):
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
        booking = LibraryBooking.objects.get(student=user, status="approved")
    except LibraryBooking.DoesNotExist:
        return Response({"error": "No active library booking found."}, status=400)

    today = date.today()
    current_month = today.replace(day=1)
    is_first_invoice = not LibraryMonthlyInvoice.objects.filter(booking=booking).exists()

    # Prevent duplicate
    if LibraryMonthlyInvoice.objects.filter(booking=booking, month=current_month).exists():
        return Response({"error": "Invoice already generated for this month."}, status=400)

    # Prevent early generation
    if not is_first_invoice:
        last_invoice = LibraryMonthlyInvoice.objects.filter(booking=booking).order_by('-month').first()
        year, month = last_invoice.month.year, last_invoice.month.month
        last_day = monthrange(year, month)[1]
        invoice_end_date = last_invoice.month.replace(day=last_day)

        days_left = (invoice_end_date - today).days
        if days_left > 2:
            return Response({
                "error": f"Next invoice can only be generated in last 3 days of current invoice cycle. {days_left} days remaining."
            }, status=400)

    fees = LibraryMonthlyFee.objects.last()
    if not fees:
        return Response({"error": "Library fee settings not configured."}, status=500)

    from hostel.models import HostelBooking
    has_hostel = HostelBooking.objects.filter(student=user, status__in=['approved', 'pending']).exists()

    # invoice_start = booking.start_date if is_first_invoice else (last_invoice.month + timedelta(days=30))

    if is_first_invoice:
        day = booking.start_date.day
        monthly_fee = 600 if day <= 15 else 300
        deposit = 0 if has_hostel else fees.deposit_amount
    else:
        monthly_fee = fees.monthly_fee
        deposit = 0

    total = monthly_fee + deposit

    invoice = LibraryMonthlyInvoice.objects.create(
        booking=booking,
        invoice_id=generate_invoice_id("LI", booking.id, current_month),
        month=current_month,
        amount=monthly_fee,
        deposit=deposit,
        total=total,
        invoice_expired=False
    )

    return Response(LibraryMonthlyInvoiceSerializer(invoice).data)


@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('seat_id', openapi.IN_QUERY, description="Seat ID", type=openapi.TYPE_INTEGER)
    ],
    responses={200: 'Billing summary response'}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def library_billing_summary(request):
    seat_id = request.GET.get('seat_id')
    fee_config = LibraryMonthlyFee.objects.last()
    if not seat_id or not fee_config:
        return Response({'error': 'Seat or fee config missing'}, status=400)

    student = request.user
    has_hostel_booking = HostelBooking.objects.filter(
        student=student, status__in=['pending', 'approved']
    ).exists()

    # Determine monthly fee
    today = timezone.now().date()
    day = today.day

    monthly_fee = 600 if day <= 15 else 300
    deposit = 0 if has_hostel_booking else fee_config.deposit_amount

    return Response({
        'monthly_fee': monthly_fee,
        'deposit_amount': deposit,
        'total': monthly_fee + deposit
    })


@swagger_auto_schema(
    method='get',
    operation_description="Student: Get current library booking status (active/inactive)",
    tags=["student-booking-status"],
    responses={200: openapi.Response(description="Booking status")}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_library_booking_status(request):
    user = request.user
    has_active = LibraryBooking.objects.filter(student=user, status='approved').exists()
    return Response({"status": "active" if has_active else "inactive"})


@swagger_auto_schema(
    method='get',
    operation_description="Download library monthly invoice PDF by invoice ID",
    responses={200: "PDF invoice", 404: "Invoice not found"}
)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def download_library_invoice_pdf(request, invoice_id):
    try:
        invoice = LibraryMonthlyInvoice.objects.get(id=invoice_id, booking__student=request.user)
    except LibraryMonthlyInvoice.DoesNotExist:
        return Response({"detail": "Invoice not found."}, status=404)

    pdf_buffer = generate_library_invoice_pdf(invoice)
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=library_invoice_{invoice.invoice_id}.pdf'
    return response


class MyLibraryInvoicesView(ListAPIView):
    serializer_class = LibraryMonthlyInvoiceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = LibraryInvoiceFilter

    def get_queryset(self):
        return LibraryMonthlyInvoice.objects.filter(booking__student=self.request.user)


class AdminLibraryInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LibraryMonthlyInvoice.objects.select_related('booking__student', 'booking__seat').all()
    serializer_class = LibraryInvoiceAdminSerializer
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
    operation_description="Mark a library invoice as paid (Admin only)",
    responses={200: "Marked as paid", 404: "Invoice not found"}
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def mark_library_invoice_paid(request, invoice_id):
    from .models import LibraryMonthlyInvoice
    try:
        invoice = LibraryMonthlyInvoice.objects.get(id=invoice_id)
        invoice.is_paid = True
        invoice.paid_on = timezone.now()
        invoice.save()
        return Response({"detail": "Invoice marked as paid."})
    except LibraryMonthlyInvoice.DoesNotExist:
        return Response({"error": "Invoice not found."}, status=404)


from datetime import date, timedelta
from .models import LibraryMonthlyInvoice


def reset_expired_paid_flags():
    today = date.today()
    invoices = LibraryMonthlyInvoice.objects.filter(is_paid=True)

    for invoice in invoices:
        if today > (invoice.month + timedelta(days=30)):
            invoice.is_paid = False
            invoice.save()


@swagger_auto_schema(
    method='post',
    operation_description="Admin: Generate invoices for all approved library bookings for current month",
    responses={200: "Invoices generated", 400: "No eligible bookings", 500: "Error occurred"}
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def generate_library_invoices_bulk(request):
    from calendar import monthrange
    from datetime import date
    today = date.today()
    current_month = today.replace(day=1)

    from .models import LibraryBooking, LibraryMonthlyInvoice, LibraryMonthlyFee
    from core.utils.invoice_utils import generate_invoice_id
    from hostel.models import HostelBooking

    approved_bookings = LibraryBooking.objects.filter(status='approved')
    fees = LibraryMonthlyFee.objects.last()
    if not fees:
        return Response({"error": "Library fee settings not configured."}, status=500)

    count = 0
    for booking in approved_bookings:
        if LibraryMonthlyInvoice.objects.filter(booking=booking, month=current_month).exists():
            continue

        is_first_invoice = not LibraryMonthlyInvoice.objects.filter(booking=booking).exists()
        has_hostel = HostelBooking.objects.filter(student=booking.student, status__in=['approved', 'pending']).exists()

        if is_first_invoice:
            day = booking.start_date.day
            monthly_fee = 600 if day <= 15 else 300
            deposit = 0 if has_hostel else fees.deposit_amount
        else:
            monthly_fee = fees.monthly_fee
            deposit = 0

        total = monthly_fee + deposit

        LibraryMonthlyInvoice.objects.create(
            booking=booking,
            invoice_id=generate_invoice_id("LI", booking.id, current_month),
            month=current_month,
            amount=monthly_fee,
            deposit=deposit,
            total=total,
            invoice_expired=False
        )
        count += 1

    return Response({"message": f"{count} library invoices generated."})


# ========= SWITCH VIEWS (LIBRARY) =========


class LibraryAvailableSwitchRequestViewSet(viewsets.ModelViewSet):
    """
    Handles seat switch requests for Library (Available Seat Switching)
    - Students can request to move to a specific available seat.
    - Admin approves/rejects requests.
    - Real-time UI updates via WebSocket after commit.
    """
    queryset = LibraryAvailableSwitchRequest.objects.select_related(
        'booking__student', 'booking__seat', 'target_seat'
    )
    serializer_class = LibraryAvailableSwitchRequestSerializer
    filterset_fields = ['status']

    def get_permissions(self):
        if self.action in ['create', 'list', 'retrieve', 'cancel']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', '') == 'admin':
            return self.queryset.order_by('-created_at')
        return self.queryset.filter(booking__student=user).order_by('-created_at')

    # ---------------------------
    # CREATE (Student)
    # ---------------------------
    def create(self, request, *args, **kwargs):
        """
        Create a new switch request for a target available seat.
        One pending switch per student is allowed.
        """
        return super().create(request, *args, **kwargs)

    # ---------------------------
    # APPROVE (Admin)
    # ---------------------------
    @swagger_auto_schema(method='post', operation_description="Admin: Approve available seat switch request")
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        """Approve the seat switch (atomic + post-commit WebSocket broadcast)."""
        sr = self.get_object()

        if sr.status != 'pending':
            return Response({"error": "This request is already processed."}, status=400)

        booking = sr.booking
        from_seat = booking.seat
        to_seat = sr.target_seat

        # Lock both seats to prevent race conditions
        LibrarySeat.objects.select_for_update().filter(id__in=[from_seat.id, to_seat.id])

        if to_seat.is_booked:
            return Response({"error": "Target seat is no longer available."}, status=400)
        if booking.status != 'approved':
            return Response({"error": "Only approved bookings can be switched."}, status=400)
        if from_seat.id == to_seat.id:
            return Response({"error": "Same seat cannot be switched."}, status=400)

        # ---- Seat Switching ----
        from_seat.is_booked = False
        from_seat.save(update_fields=['is_booked'])

        booking.seat = to_seat
        booking.save(update_fields=['seat'])

        to_seat.is_booked = True
        to_seat.save(update_fields=['is_booked'])

        # ---- Update Request ----
        sr.status = 'approved'
        sr.approved_by = request.user
        sr.approved_at = timezone.now()
        sr.save(update_fields=['status', 'approved_by', 'approved_at'])

        # ---- Log History ----
        LibraryAvailableSwitchHistory.objects.create(
            booking=booking,
            from_seat=from_seat,
            to_seat=to_seat,
            action='approved',
            actor=request.user,
            remarks=sr.remarks or ''
        )

        # ---- Email Notification ----
        try:
            send_custom_email(
                to_email=booking.student.email,
                subject="Library Switch Approved",
                message=f"Your seat switch has been approved.\n"
                        f"New Seat: {to_seat.seat_number}"
            )
        except Exception as e:
            print("Email failed:", e)

        # ---- WebSocket Broadcast (After Commit) ----
        def after_commit():
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "live_seat_updates",
                    {
                        "type": "send_seat_update",
                        "data": {
                            "type": "library_seat_switched",
                            "old_seat_id": from_seat.id,
                            "new_seat_id": to_seat.id,
                            "booking_id": booking.id,
                            "student": booking.student.username,
                            "status": "approved",
                        },
                    },
                )
            except Exception as e:
                print("WebSocket broadcast failed:", e)

        transaction.on_commit(after_commit)
        return Response({"detail": "Seat switched successfully."})

    # ---------------------------
    # REJECT (Admin)
    # ---------------------------
    @swagger_auto_schema(
        method='post',
        operation_description="Admin: Reject available seat switch request",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={'remarks': openapi.Schema(type=openapi.TYPE_STRING)}
        ),
    )
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        sr = self.get_object()

        if sr.status != 'pending':
            return Response({"error": "Request already processed."}, status=400)

        sr.status = 'rejected'
        sr.remarks = (request.data.get('remarks') or '').strip() or 'Rejected by admin.'
        sr.approved_by = request.user
        sr.approved_at = timezone.now()
        sr.save(update_fields=['status', 'remarks', 'approved_by', 'approved_at'])

        LibraryAvailableSwitchHistory.objects.create(
            booking=sr.booking,
            from_seat=sr.booking.seat,
            to_seat=sr.target_seat,
            action='rejected',
            actor=request.user,
            remarks=sr.remarks,
        )

        # Email rejection notice
        try:
            send_custom_email(
                to_email=sr.booking.student.email,
                subject="Library Switch Rejected",
                message=f"Your seat switch request was rejected.\nRemarks: {sr.remarks}",
            )
        except Exception as e:
            print("Email failed:", e)

        return Response({"detail": "Switch request rejected successfully."})

    # ---------------------------
    # CANCEL (Student/Admin)
    # ---------------------------
    @swagger_auto_schema(
        method='post',
        operation_description="Cancel own available switch request (Student/Admin)",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={'remarks': openapi.Schema(type=openapi.TYPE_STRING)}
        ),
    )
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        sr = self.get_object()
        user = request.user

        if sr.status != 'pending':
            return Response({"error": "Only pending requests can be cancelled."}, status=400)

        if getattr(user, 'role', '') != 'admin' and sr.booking.student != user:
            raise PermissionDenied("You are not allowed to cancel this request.")

        sr.status = 'cancelled'
        sr.remarks = (request.data.get('remarks') or '').strip() or 'Cancelled by user.'
        sr.save(update_fields=['status', 'remarks'])

        LibraryAvailableSwitchHistory.objects.create(
            booking=sr.booking,
            from_seat=sr.booking.seat,
            to_seat=sr.target_seat,
            action='cancelled',
            actor=user,
            remarks=sr.remarks,
        )

        # Email cancellation notice
        try:
            send_custom_email(
                to_email=sr.booking.student.email,
                subject="Library Switch Cancelled",
                message=f"Your seat switch request has been cancelled.\nRemarks: {sr.remarks}",
            )
        except Exception as e:
            print("Email failed:", e)

        return Response({"detail": "Switch request cancelled successfully."})


class LibraryMutualSwitchRequestViewSet(viewsets.ModelViewSet):
    """
    Handles all library mutual switch requests between students.

    Supports:
    - Student open/targeted request creation
    - Admin match-and-approve mutual swap
    - Reject, Cancel, and History logging
    - Real-time seat updates (WebSocket after commit)
    """
    queryset = LibraryMutualSwitchRequest.objects.select_related(
        'requester_booking__student', 'requester_booking__seat',
        'partner_booking__student', 'partner_booking__seat'
    )
    serializer_class = LibraryMutualSwitchRequestSerializer
    filterset_fields = ['status']

    def get_permissions(self):
        if self.action in ['create', 'list', 'retrieve', 'cancel']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', '') == 'admin':
            return self.queryset.order_by('-created_at')
        return self.queryset.filter(requester_booking__student=user).order_by('-created_at')

    # ---------------------------
    # Create new mutual request
    # ---------------------------
    def create(self, request, *args, **kwargs):
        """
        Students can create an open or targeted mutual switch request.
        - open: partner_booking=None
        - targeted: partner_booking=other booking
        """
        return super().create(request, *args, **kwargs)

    # ---------------------------
    # Admin Match and Approve
    # ---------------------------
    @swagger_auto_schema(
        method='post',
        operation_description="Admin: Match two OPEN or targeted mutual requests and approve seat swap atomically.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['request_a_id', 'request_b_id'],
            properties={
                'request_a_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                'request_b_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                'remarks': openapi.Schema(type=openapi.TYPE_STRING),
            },
        ),
        responses={200: "Mutual switch approved", 400: "Validation error"}
    )
    @action(detail=False, methods=['post'], url_path='match-and-approve')
    @transaction.atomic
    def match_and_approve(self, request):
        """Admin manually matches two mutual requests and approves the swap."""
        a_id = request.data.get('request_a_id')
        b_id = request.data.get('request_b_id')
        remarks = (request.data.get('remarks') or '').strip()

        try:
            req_a = LibraryMutualSwitchRequest.objects.select_for_update().get(id=a_id, status='pending')
            req_b = LibraryMutualSwitchRequest.objects.select_for_update().get(id=b_id, status='pending')
        except LibraryMutualSwitchRequest.DoesNotExist:
            return Response({"error": "Both requests must be valid and pending."}, status=400)

        if req_a.requester_booking_id == req_b.requester_booking_id:
            return Response({"error": "Cannot match the same booking."}, status=400)

        booking_a = req_a.requester_booking
        booking_b = req_b.requester_booking

        # Validate both bookings
        if booking_a.status != 'approved' or booking_b.status != 'approved':
            return Response({"error": "Both bookings must be approved."}, status=400)

        seat_a = booking_a.seat
        seat_b = booking_b.seat
        if not seat_a or not seat_b:
            return Response({"error": "Both bookings must have valid seats."}, status=400)

        # Lock seats atomically
        LibrarySeat.objects.select_for_update().filter(id__in=[seat_a.id, seat_b.id])

        # Perform the swap
        booking_a.seat, booking_b.seat = seat_b, seat_a
        booking_a.save(update_fields=['seat'])
        booking_b.save(update_fields=['seat'])

        # Update both requests
        for req in (req_a, req_b):
            req.status = 'approved'
            req.approved_by = request.user
            req.approved_at = timezone.now()
            req.remarks = remarks or req.remarks
            req.save(update_fields=['status', 'approved_by', 'approved_at', 'remarks'])

        # Record history
        LibraryMutualSwitchHistory.objects.create(
            booking_a=booking_a, booking_b=booking_b,
            from_seat_a=seat_a, to_seat_a=booking_a.seat,
            from_seat_b=seat_b, to_seat_b=booking_b.seat,
            action='approved', actor=request.user, remarks=remarks
        )

        # Email notifications (non-blocking)
        for bk in (booking_a, booking_b):
            try:
                send_custom_email(
                    to_email=bk.student.email,
                    subject="Library Mutual Switch Approved",
                    message=f"Your seat has been switched successfully to {bk.seat.seat_number}."
                )
            except Exception as e:
                print("Email send failed:", e)

        # ---------------------------
        # WebSocket broadcast AFTER COMMIT
        # ---------------------------
        def broadcast_after_commit():
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "live_seat_updates",
                    {
                        "type": "send_seat_update",
                        "data": {
                            "type": "library_mutual_switch",
                            "booking_a_id": booking_a.id,
                            "booking_b_id": booking_b.id,
                            "seat_a_id": seat_a.id,
                            "seat_b_id": seat_b.id,
                            "new_seat_a": booking_a.seat.id,
                            "new_seat_b": booking_b.seat.id,
                            "status": "approved"
                        }
                    }
                )
            except Exception as e:
                print("WebSocket broadcast failed:", e)

        transaction.on_commit(broadcast_after_commit)

        return Response({"detail": "Mutual switch approved successfully and broadcast sent."})

    # ---------------------------
    # Reject mutual switch
    # ---------------------------
    @swagger_auto_schema(
        method='post',
        operation_description="Admin: Reject a pending mutual switch request",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={'remarks': openapi.Schema(type=openapi.TYPE_STRING)}
        ),
    )
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        req = self.get_object()
        if req.status != 'pending':
            return Response({"error": "Already processed."}, status=400)

        req.status = 'rejected'
        req.remarks = (request.data.get('remarks') or '').strip() or 'Rejected by admin'
        req.approved_by = request.user
        req.approved_at = timezone.now()
        req.save(update_fields=['status', 'remarks', 'approved_by', 'approved_at'])

        LibraryMutualSwitchHistory.objects.create(
            booking_a=req.requester_booking,
            booking_b=req.partner_booking,
            from_seat_a=req.requester_booking.seat,
            to_seat_a=req.partner_booking.seat if req.partner_booking else None,
            from_seat_b=req.partner_booking.seat if req.partner_booking else None,
            to_seat_b=req.requester_booking.seat,
            action='rejected', actor=request.user, remarks=req.remarks
        )

        try:
            send_custom_email(
                to_email=req.requester_booking.student.email,
                subject="Library Mutual Switch Rejected",
                message=f"Your mutual switch request was rejected. Remarks: {req.remarks}"
            )
        except Exception as e:
            print("Email failed:", e)

        return Response({"detail": "Mutual switch request rejected."})

    # ---------------------------
    # Cancel mutual switch
    # ---------------------------
    @swagger_auto_schema(
        method='post',
        operation_description="Student/Admin: Cancel a pending mutual switch request",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={'remarks': openapi.Schema(type=openapi.TYPE_STRING)}
        ),
    )
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        req = self.get_object()
        user = request.user

        if req.status != 'pending':
            return Response({"error": "Only pending requests can be cancelled."}, status=400)

        if getattr(user, 'role', '') != 'admin' and req.requester_booking.student != user:
            raise PermissionDenied("You are not allowed to cancel this request.")

        req.status = 'cancelled'
        req.remarks = (request.data.get('remarks') or '').strip() or 'Cancelled by user'
        req.save(update_fields=['status', 'remarks'])

        LibraryMutualSwitchHistory.objects.create(
            booking_a=req.requester_booking,
            booking_b=req.partner_booking,
            from_seat_a=req.requester_booking.seat,
            to_seat_a=req.partner_booking.seat if req.partner_booking else None,
            from_seat_b=req.partner_booking.seat if req.partner_booking else None,
            to_seat_b=req.requester_booking.seat,
            action='cancelled', actor=user, remarks=req.remarks
        )

        return Response({"detail": "Mutual switch request cancelled successfully."})


# ===== HISTORY VIEWS (LIBRARY) =====

class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, 'role', '') == 'admin'


class LibraryAvailableSwitchHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LibraryAvailableSwitchHistory.objects.select_related(
        'booking__student', 'from_seat', 'to_seat'
    ).order_by('-created_at')
    serializer_class = LibraryAvailableSwitchHistorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['action']

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if getattr(u, 'role', '') == 'admin':
            return qs
        return qs.filter(booking__student=u)


class LibraryMutualSwitchHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LibraryMutualSwitchHistory.objects.select_related(
        'booking_a__student', 'booking_b__student'
    ).order_by('-created_at')
    serializer_class = LibraryMutualSwitchHistorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['action']

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if getattr(u, 'role', '') == 'admin':
            return qs
        # return qs.filter(models.Q(booking_a__student=u) | models.Q(booking_b__student=u))
        return qs.filter(Q(booking_a__student=u) | Q(booking_b__student=u))

