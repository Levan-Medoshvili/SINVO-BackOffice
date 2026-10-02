from django.db import models
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

class CustomUserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("The Username field must be set")

        # If email is provided, normalize it
        if 'email' in extra_fields:
            extra_fields['email'] = self.normalize_email(extra_fields['email'])

        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(username, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # This is now the main login field
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True, null=True)

    name = models.CharField(max_length=255)
    surname = models.CharField(max_length=255)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    profile_image = models.ImageField(null=True, blank=True, upload_to='profiles/', default='profiles/default.jpg')

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    # Tells Django which field to use for login
    USERNAME_FIELD = 'username'
    # Fields asked for when running 'createsuperuser' (excluding username/password)
    REQUIRED_FIELDS = ['name', 'surname']

    def __str__(self):
        return self.username

class Group(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

class ActionPermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True) # e.g., 'edit_users'
    description = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True)

class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    permissions = models.ManyToManyField(ActionPermission)
    description = models.TextField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

class UserRoleAssignment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assignments')
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)
