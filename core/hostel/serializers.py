from django.utils import timezone
from rest_framework import serializers
from .models import HostelRoom, HostelBed, HostelBooking, HostelMonthlyFee, HostelMonthlyInvoice, \
    HostelAvailableSwitchRequest, HostelMutualSwitchRequest, HostelAvailableSwitchHistory, HostelMutualSwitchHistory
from users.serializers import UserSerializer


class HostelRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = HostelRoom
        fields = '__all__'


class HostelBedSerializer(serializers.ModelSerializer):
    room = HostelRoomSerializer(read_only=True)
    room_id = serializers.PrimaryKeyRelatedField(
        queryset=HostelRoom.objects.all(), source='room', write_only=True
    )
    status = serializers.SerializerMethodField()

    class Meta:
        model = HostelBed
        fields = [
            'id', 'room', 'bed_number', 'description', 'is_booked', 'room_id',
            'status', 'pending_count'
        ]

    def get_status(self, obj):
        from hostel.models import HostelBooking
        if obj.is_booked:
            return "Booked"
        pending = HostelBooking.objects.filter(bed=obj, status='pending').exists()
        return "Pending" if pending else "Available"

    pending_count = serializers.SerializerMethodField()

    def get_pending_count(self, obj):
        from .models import HostelBooking
        return HostelBooking.objects.filter(bed=obj, status='pending').count()


class HostelBookingSerializer(serializers.ModelSerializer):
    bed_id = serializers.PrimaryKeyRelatedField(
        source='bed',
        queryset=HostelBed.objects.all(),
        write_only=True
    )
    bed = HostelBedSerializer(read_only=True)
    student = UserSerializer(read_only=True)
    aadhaar_front_photo = serializers.ImageField(required=False, allow_null=True, write_only=True)
    aadhaar_back_photo = serializers.ImageField(required=False, allow_null=True, write_only=True)
    billing_summary = serializers.SerializerMethodField()
    purpose_of_joining = serializers.CharField(required=True)

    class Meta:
        model = HostelBooking
        fields = '__all__'
        read_only_fields = [
            'id', 'student', 'bed', 'status', 'approved_by', 'approved_at', 'purpose_of_joining',
            'monthly_fee', 'deposit_amount', 'created_at', 'billing_summary'
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
        from .models import HostelMonthlyFee
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        user = self.context['request'].user

        # Fetch latest monthly fee config
        fee_config = HostelMonthlyFee.objects.order_by('-effective_from').first()
        if not fee_config:
            raise serializers.ValidationError("Monthly fee config not found. Please contact admin.")

        today = timezone.now().date()
        day = today.day

        if day <= 10:
            monthly_fee = 1500
        elif day <= 20:
            monthly_fee = 1000
        else:
            monthly_fee = 500

        validated_data['monthly_fee'] = monthly_fee
        validated_data['deposit_amount'] = fee_config.deposit_amount
        print(f"Billing - Fee: {monthly_fee}, Deposit: {fee_config.deposit_amount}")

        booking = HostelBooking.objects.create(
            student=user,
            status='pending',
            **validated_data
        )

        # WebSocket trigger for admin live map
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "live_seat_updates",
            {
                "type": "send_seat_update",
                "data": {
                    "type": "booking_pending",
                    "bed_id": booking.bed.id,
                    "room_id": booking.bed.room.id,
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


class HostelMonthlyFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = HostelMonthlyFee
        fields = '__all__'


# hostel/serializers.py


class HostelMonthlyInvoiceSerializer(serializers.ModelSerializer):
    booking_type = serializers.SerializerMethodField()
    organisation = serializers.SerializerMethodField()
    student = serializers.SerializerMethodField()
    bed = serializers.SerializerMethodField()
    room = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()

    class Meta:
        model = HostelMonthlyInvoice

        fields = [
            'id', 'invoice_id', 'booking_type', 'organisation', 'student',
            'month', 'amount', 'deposit', 'total', 'is_paid', 'generated_on',
            'room', 'bed', 'start_date'
        ]

    def get_booking_type(self, obj):
        return "hostel"

    def get_organisation(self, obj):
        return "Bussiness Track Hostel & Library"

    def get_student(self, obj):
        student = obj.booking.student
        return {
            "name": f"{student.first_name} {student.last_name}".strip(),
            "phone": student.phone_number
        }

    def get_bed(self, obj):
        return obj.booking.bed.bed_number if obj.booking.bed else None

    def get_room(self, obj):
        return obj.booking.bed.room.room_number if obj.booking.bed and obj.booking.bed.room else None

    def get_start_date(self, obj):
        return obj.booking.start_date


class HostelInvoiceAdminSerializer(serializers.ModelSerializer):
    student_id = serializers.IntegerField(source='booking.student.id', read_only=True)
    student_name = serializers.CharField(source='booking.student.get_full_name', read_only=True)
    student_username = serializers.CharField(source='booking.student.username', read_only=True)
    room_number = serializers.CharField(source='booking.bed.room.room_number', read_only=True)
    bed_number = serializers.CharField(source='booking.bed.bed_number', read_only=True)

    class Meta:
        model = HostelMonthlyInvoice
        fields = [
            'id', 'invoice_id', 'student_id', 'student_username', 'student_name',
            'room_number', 'bed_number', 'month', 'amount', 'deposit',
            'total', 'is_paid', 'generated_on', 'booking_id'
        ]


# ========= SWITCH SERIALIZERS (HOSTEL) =========

class HostelAvailableSwitchRequestSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    current_room = serializers.SerializerMethodField()
    current_bed = serializers.SerializerMethodField()
    target_room = serializers.SerializerMethodField()
    target_bed_number = serializers.SerializerMethodField()

    class Meta:
        model = HostelAvailableSwitchRequest
        fields = ['id', 'booking', 'student', 'current_room', 'current_bed',
                  'target_bed', 'target_room', 'target_bed_number',
                  'status', 'remarks', 'created_at', 'approved_at']
        read_only_fields = ['booking', 'status', 'created_at', 'approved_at']

    def get_student(self, obj):
        s = obj.booking.student
        return {"id": s.id, "username": s.username, "name": s.get_full_name()}

    def get_current_room(self, obj):
        return obj.booking.bed.room.room_number if obj.booking and obj.booking.bed else None

    def get_current_bed(self, obj):
        return obj.booking.bed.bed_number if obj.booking and obj.booking.bed else None

    def get_target_room(self, obj):
        return obj.target_bed.room.room_number if obj.target_bed and obj.target_bed.room else None

    def get_target_bed_number(self, obj):
        return obj.target_bed.bed_number if obj.target_bed else None

    def validate(self, attrs):
        request = self.context['request']
        user = request.user

        # Must have an approved booking
        from .models import HostelBooking, HostelBed
        try:
            booking = HostelBooking.objects.get(student=user, status='approved')
        except HostelBooking.DoesNotExist:
            raise serializers.ValidationError("No approved hostel booking found.")

        target_bed = attrs.get('target_bed')
        if target_bed.is_booked:
            raise serializers.ValidationError("Target bed is not available.")
        if booking.bed_id == target_bed.id:
            raise serializers.ValidationError("You are already on this bed.")

        # One pending request per student (strict) across both types
        if HostelAvailableSwitchRequest.objects.filter(booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending available switch request.")
        if HostelMutualSwitchRequest.objects.filter(requester_booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending mutual switch request.")

        attrs['booking'] = booking
        return attrs


class HostelMutualSwitchRequestSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    partner_student = serializers.SerializerMethodField()
    current_room = serializers.SerializerMethodField()
    current_bed = serializers.SerializerMethodField()
    partner_room = serializers.SerializerMethodField()
    partner_bed = serializers.SerializerMethodField()

    mutual_booking_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = HostelMutualSwitchRequest
        fields = ['id', 'requester_booking', 'student',
                  'partner_booking', 'partner_student',
                  'current_room', 'current_bed', 'partner_room', 'partner_bed',
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

    def get_current_room(self, obj):
        return obj.requester_booking.bed.room.room_number if obj.requester_booking and obj.requester_booking.bed else None

    def get_current_bed(self, obj):
        return obj.requester_booking.bed.bed_number if obj.requester_booking and obj.requester_booking.bed else None

    def get_partner_room(self, obj):
        return obj.partner_booking.bed.room.room_number if obj.partner_booking and obj.partner_booking.bed else None

    def get_partner_bed(self, obj):
        return obj.partner_booking.bed.bed_number if obj.partner_booking and obj.partner_booking.bed else None

    def validate(self, attrs):
        request = self.context['request']
        user = request.user
        from .models import HostelBooking

        try:
            my_booking = HostelBooking.objects.get(student=user, status='approved')
        except HostelBooking.DoesNotExist:
            raise serializers.ValidationError("No approved hostel booking found.")

        # Pending check across both
        from .models import HostelAvailableSwitchRequest, HostelMutualSwitchRequest
        if HostelAvailableSwitchRequest.objects.filter(booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending available switch request.")
        if HostelMutualSwitchRequest.objects.filter(requester_booking__student=user, status='pending').exists():
            raise serializers.ValidationError("You already have a pending mutual switch request.")

        partner_id = attrs.pop('mutual_booking_id', None)
        partner_booking = None
        if partner_id:
            try:
                partner_booking = HostelBooking.objects.get(id=partner_id, status='approved')
            except HostelBooking.DoesNotExist:
                raise serializers.ValidationError("Partner booking not found or not approved.")

            # Self mutual => treat as OPEN
            if partner_booking.student_id == user.id:
                partner_booking = None

        attrs['requester_booking'] = my_booking
        attrs['partner_booking'] = partner_booking
        return attrs


# ===== HISTORY SERIALIZERS (HOSTEL) =====

class HostelAvailableSwitchHistorySerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    previous_room = serializers.SerializerMethodField()
    previous_bed = serializers.SerializerMethodField()
    new_room = serializers.SerializerMethodField()
    new_bed = serializers.SerializerMethodField()
    changed_on = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = HostelAvailableSwitchHistory
        fields = ['id', 'student', 'previous_room', 'previous_bed', 'new_room', 'new_bed',
                  'action', 'remarks', 'changed_on']

    def get_student(self, obj):
        s = obj.booking.student if obj.booking else None
        return s.get_full_name() if s else None

    def get_previous_room(self, obj):
        return obj.from_bed.room.room_number if obj.from_bed and obj.from_bed.room else None

    def get_previous_bed(self, obj):
        return obj.from_bed.bed_number if obj.from_bed else None

    def get_new_room(self, obj):
        return obj.to_bed.room.room_number if obj.to_bed and obj.to_bed.room else None

    def get_new_bed(self, obj):
        return obj.to_bed.bed_number if obj.to_bed else None


class HostelMutualSwitchHistorySerializer(serializers.ModelSerializer):
    student_a = serializers.SerializerMethodField()
    student_b = serializers.SerializerMethodField()
    old_bed_a = serializers.SerializerMethodField()
    old_bed_b = serializers.SerializerMethodField()
    new_bed_a = serializers.SerializerMethodField()
    new_bed_b = serializers.SerializerMethodField()
    changed_on = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = HostelMutualSwitchHistory
        fields = ['id', 'student_a', 'student_b',
                  'old_bed_a', 'old_bed_b', 'new_bed_a', 'new_bed_b',
                  'action', 'remarks', 'changed_on']

    def _student_name(self, booking):
        return booking.student.get_full_name() if booking and booking.student else None

    def get_student_a(self, obj): return self._student_name(obj.booking_a)
    def get_student_b(self, obj): return self._student_name(obj.booking_b)

    def get_old_bed_a(self, obj): return obj.from_bed_a.bed_number if obj.from_bed_a else None
    def get_old_bed_b(self, obj): return obj.from_bed_b.bed_number if obj.from_bed_b else None
    def get_new_bed_a(self, obj): return obj.to_bed_a.bed_number if obj.to_bed_a else None
    def get_new_bed_b(self, obj): return obj.to_bed_b.bed_number if obj.to_bed_b else None
