from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('student', 'Student'),
    )

    first_name = models.CharField(max_length=30)
    middle_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30)
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    # aadhar_number = models.CharField(max_length=20, default='000000000000')
    address = models.TextField(default='unknown')
    education = models.CharField(max_length=100, default='NA')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    profile_photo = models.ImageField(upload_to='profile_photos/', null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.role})"
