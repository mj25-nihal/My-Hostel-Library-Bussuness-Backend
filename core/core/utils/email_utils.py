from django.core.mail import send_mail
from django.conf import settings

def send_approval_email(student_email, student_name, booking_type):
    subject = f"{booking_type} Booking Approved"
    message = (
        f"Hello {student_name},\n\n"
        f"Your {booking_type.lower()} booking has been approved!\n"
        f"You may now proceed as per the schedule.\n\n"
        f"Regards,\nAdmin Team"
    )
    try:
        print("Sending approval email to:", student_email)
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [student_email])
        print("Email sent successfully")
    except Exception as e:
        print("Error while sending approval email:", e)

def send_rejection_email(student_email, student_name, booking_type):
    subject = f"{booking_type} Booking Rejected"
    message = (
        f"Hello {student_name},\n\n"
        f"Your {booking_type.lower()} booking has been rejected by the admin.\n"
        f"If you have any questions, please contact the administration.\n\n"
        f"Regards,\nAdmin Team"
    )
    try:
        print("Sending rejection email to:", student_email)
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [student_email])
        print("Email sent successfully")
    except Exception as e:
        print("Error while sending rejection email:", e)



def send_custom_email(subject, to_email, message):
    from_email = settings.DEFAULT_FROM_EMAIL
    send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=[to_email],
        fail_silently=True,
    )
