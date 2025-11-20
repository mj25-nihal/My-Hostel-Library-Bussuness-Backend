from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()

CATEGORY_CHOICES = [
    ('hostel', 'Hostel'),
    ('library', 'Library'),
    ('other', 'Other'),
]


class Complaint(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    screenshot = models.ImageField(upload_to='complaints/', blank=True, null=True)
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    submitted_on = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='pending')


class Suggestion(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    submitted_on = models.DateTimeField(auto_now_add=True)


class Review(models.Model):
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField()
    name = models.CharField(max_length=100)
    rating = models.IntegerField()
    is_approved = models.BooleanField(default=False)
    submitted_on = models.DateTimeField(auto_now_add=True)


class ContactMessage(models.Model):
    first_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} - {self.email}"


# models.py

class AchievementBlog(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    images = models.ImageField(upload_to='achievements/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.title
