from django.utils import timezone
from rest_framework import serializers
from .models import LibrarySeat, TimeSlot, LibraryBooking, LibraryMonthlyFee, LibraryMonthlyInvoice, \
    LibraryAvailableSwitchRequest, LibraryMutualSwitchRequest, LibraryAvailableSwitchHistory, LibraryMutualSwitchHistory
from users.serializers import UserSerializer


class LibrarySeatSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = LibrarySeat
        fields = [
            'id', 'seat_number', 'description', 'is_booked', 'status', 'pending_count'
        ]

    def get_status(self, obj):
        from .models import LibraryBooking
        if obj.is_booked:
            return "Booked"
        if LibraryBooking.objects.filter(seat=obj, status='pending').exists():
            return "Pending"
        return "Available"

    pending_count = serializers.SerializerMethodField()

    def get_pending_count(self, obj):
        from .models import LibraryBooking
        return LibraryBooking.objects.filter(seat=obj, status='pending').count()


class TimeSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeSlot
        fields = '__all__'


class LibraryBookingSerializer(serializers.ModelSerializer):
    seat_id = serializers.PrimaryKeyRelatedField(
        source='seat',
        queryset=LibrarySeat.objects.all(),
        write_only=True
    )
    seat = LibrarySeatSerializer(read_only=True)
    student = UserSerializer(read_only=True)
    aadhaar_front_photo = serializers.ImageField(required=False, allow_null=True, write_only=True)
    aadhaar_back_photo = serializers.ImageField(required=False, allow_null=True, write_only=True)
    billing_summary = serializers.SerializerMethodField()
    purpose_of_joining = serializers.CharField(required=True)

    class Meta:
        model = LibraryBooking
        fields = '__all__'
        read_only_fields = [
            'id', 'student', 'seat', 'status', 'purpose_of_joining',
            'monthly_fee', 'deposit_amount', 'created_at',
            'billing_summary'
        ]

    def validate(self, data):
        request = self.context.get('request')
        user = request.user

        if request.method == 'POST':
            aadhaar_present = False

            from hostel.models import HostelBooking
            from library.models import LibraryBooking

            # Check hostel booking
            hostel = HostelBooking.objects.filter(student=user, status__in=['approved', 'pending']).last()
            if hostel and hostel.aadhaar_front_photo and hostel.aadhaar_back_photo:
                aadhaar_present = True

            # Check library booking
            library = LibraryBooking.objects.filter(student=user, status__in=['approved', 'pending']).last()
            if library and library.aadhaar_front_photo and library.aadhaar_back_photo:
                aadhaar_present = True

            # Aadhaar required only if not already present
            if not aadhaar_present:
                if not data.get('aadhaar_front_photo') or not data.get('aadhaar_back_photo'):
                    raise serializers.ValidationError("Aadhaar front and back photo are required.")

            # Profile photo logic
            if not user.profile_photo and not data.get('aadhaar_front_photo'):
                raise serializers.ValidationError("Profile photo or Aadhaar front is required.")

        return data

    def create(self, validated_data):
        from .models import LibraryMonthlyFee
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        user = self.context['request'].user

        # Get latest fee config
        fee_config = LibraryMonthlyFee.objects.order_by('-effective_from').first()
        if not fee_config:
            raise serializers.ValidationError("Monthly fee config not found. Please contact admin.")

        today = timezone.now().date()
        day = today.day

        if day <= 15:
            monthly_fee = 600
        else:
            monthly_fee = 300

        # Check if hostel booking exists
        from hostel.models import HostelBooking
        has_hostel = HostelBooking.objects.filter(student=user, status__in=['approved', 'pending']).exists()

        deposit = 0 if has_hostel else fee_config.deposit_amount

        validated_data['monthly_fee'] = monthly_fee
        validated_data['deposit_amount'] = deposit
        print(f"Billing - Fee: {monthly_fee}, Deposit: {deposit}")

        booking = LibraryBooking.objects.create(
            student=user,
            status='pending',
            **validated_data
        )

        # Notify via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "live_seat_updates",
            {
                "type": "send_seat_update",
                "data": {
                    "type": "library_booking_pending",
                    "seat_id": booking.seat.id,
                    "is_booked": False,
                    "student": booking.student.username,
                }
            }
        )

        return booking

    def get_billing_summary(self, obj):
        if obj.status != 'approved':
            return {}

        from datetime import date
        from dateutil.relativedelta import relativedelta

        today = date.today()
        rdelta = relativedelta(today, obj.start_date)
        months = rdelta.years * 12 + rdelta.months + (1 if rdelta.days >= 0 else 0)

        total_due = (obj.monthly_fee or 0) * months + (obj.deposit_amount or 0)

        return {
            "months_active": months,
            "monthly_fee": obj.monthly_fee,
            "deposit": obj.deposit_amount,
            "total_due": total_due
        }


class LibraryMonthlyFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LibraryMonthlyFee
        fields = '__all__'


# library/serializers.py


class LibraryMonthlyInvoiceSerializer(serializers.ModelSerializer):
    booking_type = serializers.SerializerMethodField()
    organisation = serializers.SerializerMethodField()
    student = serializers.SerializerMethodField()
    seat = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()

    class Meta:
        model = LibraryMonthlyInvoice
        fields = [
            'id', 'invoice_id', 'booking_type', 'organisation', 'student',
            'month', 'amount', 'deposit', 'total', 'is_paid', 'generated_on', 'seat', 'start_date'
        ]

    def get_booking_type(self, obj):
        return "library"

    def get_organisation(self, obj):
        return "Bussiness Track Hostel & Library"

    def get_student(self, obj):
        student = obj.booking.student
        return {
            "name": f"{student.first_name} {student.last_name}".strip(),
            "phone": student.phone_number
        }

    def get_seat(self, obj):
        return obj.booking.seat.seat_number if obj.booking.seat else None

    def get_start_date(self, obj):
        return obj.booking.start_date


class LibraryInvoiceAdminSerializer(serializers.ModelSerializer):
    student_id = serializers.IntegerField(source='booking.student.id', read_only=True)
    student_name = serializers.CharField(source='booking.student.get_full_name', read_only=True)
    student_username = serializers.CharField(source='booking.student.username', read_only=True)
    seat_number = serializers.CharField(source='booking.seat.seat_number', read_only=True)

    class Meta:
        model = LibraryMonthlyInvoice
        fields = [
            'id', 'invoice_id', 'student_id', 'student_username', 'student_name',
            'seat_number', 'month', 'amount', 'deposit',
            'total', 'is_paid', 'generated_on', 'booking_id'
        ]


# ========= SWITCH SERIALIZERS (LIBRARY) =========

class LibraryAvailableSwitchRequestSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    current_seat = serializers.SerializerMethodField()
    target_seat_number = serializers.SerializerMethodField()

    class Meta:
        model = LibraryAvailableSwitchRequest
        fields = ['id', 'booking', 'student', 'current_seat', 'target_seat', 'target_seat_number',
                  'status', 'remarks', 'created_at', 'approved_at']
        read_only_fields = ['booking', 'status', 'created_at', 'approved_at']

    def get_student(self, obj):
        s = obj.booking.student
        return {"id": s.id, "username": s.username, "name": s.get_full_name()}

    def get_current_seat(self, obj):
        return obj.booking.seat.seat_number if obj.booking and obj.booking.seat else None

    def get_target_seat_number(self, obj):
        return obj.target_seat.seat_number if obj.target_seat else None

    def validate(self, attrs):
        request = self.context['request']
        user = request.user
        from .models import LibraryBooking

        try:
            booking = LibraryBooking.objects.get(student=user, status='approved')
        except LibraryBooking.DoesNotExist:
            raise serializers.ValidationError("No approved library booking found.")

        target_seat = attrs.get('target_seat')
        if target_seat.is_booked:
            raise serializers.ValidationError("Target seat is not available.")
        if booking.seat_id == target_seat.id:
            raise serializers.ValidationError("You are already on this seat.")

        # one pending per student across both types
        from .models import LibraryAvailableSwitchRequest, LibraryMutualSwitchRequest
        if LibraryAvailableSwitchRequest.objects.filter(booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending available switch request.")
        if LibraryMutualSwitchRequest.objects.filter(requester_booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending mutual switch request.")

        attrs['booking'] = booking
        return attrs


class LibraryMutualSwitchRequestSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    partner_student = serializers.SerializerMethodField()
    current_seat = serializers.SerializerMethodField()
    partner_seat = serializers.SerializerMethodField()

    mutual_booking_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = LibraryMutualSwitchRequest
        fields = ['id', 'requester_booking', 'student',
                  'partner_booking', 'partner_student', 'current_seat', 'partner_seat',
                  'mutual_booking_id', 'status', 'remarks', 'created_at', 'approved_at']
        read_only_fields = ['requester_booking', 'partner_booking', 'status', 'created_at', 'approved_at']

    def get_student(self, obj):
        s = obj.requester_booking.student
        return {"id": s.id, "username": s.username, "name": s.get_full_name()}

    def get_partner_student(self, obj):
        if obj.partner_booking:
            s = obj.partner_booking.student
            return {"id": s.id, "username": s.username, "name": s.get_full_name()}
        return None

    def get_current_seat(self, obj):
        return obj.requester_booking.seat.seat_number if obj.requester_booking and obj.requester_booking.seat else None

    def get_partner_seat(self, obj):
        return obj.partner_booking.seat.seat_number if obj.partner_booking and obj.partner_booking.seat else None

    def validate(self, attrs):
        request = self.context['request']
        user = request.user
        from .models import LibraryBooking

        try:
            my_booking = LibraryBooking.objects.get(student=user, status='approved')
        except LibraryBooking.DoesNotExist:
            raise serializers.ValidationError("No approved library booking found.")

        # one pending per student across both types
        from .models import LibraryAvailableSwitchRequest, LibraryMutualSwitchRequest
        if LibraryAvailableSwitchRequest.objects.filter(booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending available switch request.")
        if LibraryMutualSwitchRequest.objects.filter(requester_booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending mutual switch request.")

        partner_id = attrs.pop('mutual_booking_id', None)
        partner_booking = None
        if partner_id:
            try:
                partner_booking = LibraryBooking.objects.get(id=partner_id, status='approved')
            except LibraryBooking.DoesNotExist:
                raise serializers.ValidationError("Partner booking not found or not approved.")

            if partner_booking.student_id == user.id:
                partner_booking = None  # self mutual => OPEN

        attrs['requester_booking'] = my_booking
        attrs['partner_booking'] = partner_booking
        return attrs


# ===== HISTORY SERIALIZERS (LIBRARY) =====

class LibraryAvailableSwitchHistorySerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    previous_seat = serializers.SerializerMethodField()
    new_seat = serializers.SerializerMethodField()
    changed_on = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = LibraryAvailableSwitchHistory
        fields = ['id', 'student', 'previous_seat', 'new_seat', 'action', 'remarks', 'changed_on']

    def get_student(self, obj):
        s = obj.booking.student if obj.booking else None
        return s.get_full_name() if s else None

    def get_previous_seat(self, obj): return obj.from_seat.seat_number if obj.from_seat else None
    def get_new_seat(self, obj): return obj.to_seat.seat_number if obj.to_seat else None


class LibraryMutualSwitchHistorySerializer(serializers.ModelSerializer):
    student_a = serializers.SerializerMethodField()
    student_b = serializers.SerializerMethodField()
    old_seat_a = serializers.SerializerMethodField()
    old_seat_b = serializers.SerializerMethodField()
    new_seat_a = serializers.SerializerMethodField()
    new_seat_b = serializers.SerializerMethodField()
    changed_on = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = LibraryMutualSwitchHistory
        fields = ['id', 'student_a', 'student_b',
                  'old_seat_a', 'old_seat_b', 'new_seat_a', 'new_seat_b',
                  'action', 'remarks', 'changed_on']

    def _student_name(self, booking):
        return booking.student.get_full_name() if booking and booking.student else None

    def get_student_a(self, obj): return self._student_name(obj.booking_a)
    def get_student_b(self, obj): return self._student_name(obj.booking_b)

    def get_old_seat_a(self, obj): return obj.from_seat_a.seat_number if obj.from_seat_a else None
    def get_old_seat_b(self, obj): return obj.from_seat_b.seat_number if obj.from_seat_b else None
    def get_new_seat_a(self, obj): return obj.to_seat_a.seat_number if obj.to_seat_a else None
    def get_new_seat_b(self, obj): return obj.to_seat_b.seat_number if obj.to_seat_b else None
