from rest_framework import serializers
from users.models import User
from .models import Complaint, Suggestion, Review,ContactMessage, AchievementBlog
from hostel.models import HostelBooking
from library.models import LibraryBooking


class StudentDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'phone',
            'address',
            'profile_photo',
            'aadhaar_front_photo',
            'aadhaar_back_photo',
        ]


class ComplaintSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_username = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()
    student_phone_number = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = '__all__'
        read_only_fields = ['submitted_by', 'submitted_on']

    def get_student_name(self, obj):
        user = obj.submitted_by
        if user:
            return f"{user.first_name} {user.last_name}".strip() or user.username
        return "Anonymous"

    def get_student_username(self, obj):
        user = obj.submitted_by
        return user.username if user else None

    def get_student_email(self, obj):
        user = obj.submitted_by
        return user.email if user else None

    def get_student_phone_number(self, obj):
        user = obj.submitted_by
        return user.phone_number if user else None


class SuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Suggestion
        fields = '__all__'
        read_only_fields = ['submitted_by', 'submitted_on']


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = '__all__'
        read_only_fields = ['name', 'is_approved', 'submitted_on']


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = '__all__'


class AdminHostelBookingSerializer(serializers.ModelSerializer):
    room = serializers.CharField(source='bed.room.room_number', default=None)
    bed = serializers.CharField(source='bed.bed_number', default=None)
    bed_description = serializers.CharField(source='bed.description', default=None)
    booking_date = serializers.DateTimeField(source='created_at', format="%d-%b-%Y %I:%M %p")

    class Meta:
        model = HostelBooking
        fields = ['id', 'room', 'bed', 'bed_description', 'start_date', 'status', 'booking_date']


class AdminLibraryBookingSerializer(serializers.ModelSerializer):
    seat = serializers.CharField(source='seat.seat_number', default=None)
    seat_description = serializers.CharField(source='seat.description', default=None)
    booking_date = serializers.DateTimeField(source='created_at', format="%d-%b-%Y %I:%M %p")

    class Meta:
        model = LibraryBooking
        fields = ['id', 'seat', 'seat_description', 'start_date', 'status', 'booking_date']


class AdminSendEmailSerializer(serializers.Serializer):
    subject = serializers.CharField()
    message = serializers.CharField()
    send_to_all = serializers.BooleanField(default=False)
    recipient_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    target_group = serializers.ChoiceField(
        choices=['hostel', 'library', 'both'], default='both'
    )

# serializers.py

class AchievementBlogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AchievementBlog
        fields = '__all__'
        read_only_fields = ['posted_by', 'created_at']
