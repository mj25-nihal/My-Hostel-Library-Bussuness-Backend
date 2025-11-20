from rest_framework import serializers
from .models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = [
            'username', 'email', 'password',
            'first_name', 'middle_name', 'last_name',
            'phone_number', 'address', 'education',
            'role', 'profile_photo'
        ]

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def validate_aadhar_number(self, value):
        if len(value) != 12 or not value.isdigit():
            raise serializers.ValidationError("Aadhar number must be a 12-digit number.")
        return value

    def validate_role(self, value):
        if value not in ['admin', 'student']:
            raise serializers.ValidationError("Invalid role. Must be 'admin' or 'student'.")
        return value


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role'] = 'admin' if user.is_staff else 'student'
        return token


class UserSerializer(serializers.ModelSerializer):
    profile_photo = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    hostel_invoice_expired = serializers.SerializerMethodField()
    hostel_invoice_paid = serializers.SerializerMethodField()
    library_invoice_expired = serializers.SerializerMethodField()
    library_invoice_paid = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'middle_name', 'last_name',
            'phone_number', 'address', 'education', 'email', 'role',
            'profile_photo', 'status',
            'hostel_invoice_expired', 'hostel_invoice_paid',
            'library_invoice_expired', 'library_invoice_paid',
        ]

    def get_profile_photo(self, obj):
        request = self.context.get('request')
        if obj.profile_photo and hasattr(obj.profile_photo, 'url'):
            return request.build_absolute_uri(obj.profile_photo.url)
        return None

    def get_status(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def get_hostel_invoice_expired(self, obj):
        from hostel.models import HostelMonthlyInvoice
        last_invoice = HostelMonthlyInvoice.objects.filter(booking__student=obj).order_by('-month').first()
        return last_invoice.invoice_expired if last_invoice else None

    def get_hostel_invoice_paid(self, obj):
        from hostel.models import HostelMonthlyInvoice
        last_invoice = HostelMonthlyInvoice.objects.filter(booking__student=obj).order_by('-month').first()
        return last_invoice.is_paid if last_invoice else None

    def get_library_invoice_expired(self, obj):
        from library.models import LibraryMonthlyInvoice
        last_invoice = LibraryMonthlyInvoice.objects.filter(booking__student=obj).order_by('-month').first()
        return last_invoice.invoice_expired if last_invoice else None

    def get_library_invoice_paid(self, obj):
        from library.models import LibraryMonthlyInvoice
        last_invoice = LibraryMonthlyInvoice.objects.filter(booking__student=obj).order_by('-month').first()
        return last_invoice.is_paid if last_invoice else None



