from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = (
        ('OWNER',   'Owner'),
        ('CASHIER', 'Cashier'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CASHIER')

    @property
    def is_owner(self):
        return self.role == 'OWNER' or self.is_superuser

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = 'OWNER'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username
