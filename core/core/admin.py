from django.contrib import admin
from .models import Complaint, Suggestion, Review, ContactMessage, AchievementBlog


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'title', 'category', 'submitted_on',
        'get_student_name', 'get_student_username', 'get_student_email', 'get_student_phone'
    ]
    list_filter = ['category', 'submitted_on']
    search_fields = ['title', 'description', 'submitted_by__username', 'submitted_by__first_name',
                     'submitted_by__email']
    readonly_fields = ['submitted_by', 'submitted_on']
    ordering = ['-submitted_on']

    def get_student_name(self, obj):
        if obj.submitted_by:
            return f"{obj.submitted_by.first_name} {obj.submitted_by.last_name}"
        return "Anonymous"

    get_student_name.short_description = 'Name'

    def get_student_username(self, obj):
        return obj.submitted_by.username if obj.submitted_by else "-"

    get_student_username.short_description = 'Username'

    def get_student_email(self, obj):
        return obj.submitted_by.email if obj.submitted_by else "-"

    get_student_email.short_description = 'Email'

    def get_student_phone(self, obj):
        return obj.submitted_by.phone_number if obj.submitted_by else "-"

    get_student_phone.short_description = 'Phone'


@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'submitted_on', 'submitted_by']
    search_fields = ['title', 'description']
    readonly_fields = ['submitted_by', 'submitted_on']
    ordering = ['-submitted_on']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'rating', 'title', 'submitted_on', 'is_approved']
    list_filter = ['rating', 'is_approved']
    search_fields = ['name', 'title', 'description']
    readonly_fields = ['submitted_on']
    list_editable = ['is_approved']
    ordering = ['-submitted_on']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'first_name', 'email', 'phone', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('first_name', 'email', 'phone', 'description')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    fieldsets = (
        ('Contact Details', {
            'fields': ('first_name', 'email', 'phone')
        }),
        ('Message Content', {
            'fields': ('description',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
        }),
    )


@admin.register(AchievementBlog)
class AchievementBlogAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'description', 'images', 'posted_by', 'created_at']
    search_fields = ['title']
