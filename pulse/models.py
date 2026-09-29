import math
import numbers
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core import exceptions
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils import timezone

from pulse import conf


def generate_share_token():
    """Return a new URL-safe share token with 256 bits of randomness."""
    return secrets.token_urlsafe(32)


def validate_not_blank(value):
    if not value.strip():
        raise exceptions.ValidationError('Enter a project name.', code='blank')


def validate_rating(value):
    """Check ``value`` against the configured scale, read at call time (#3).

    A function instead of MinValueValidator/MaxValueValidator, so the bounds
    are not frozen into the migration.
    """
    scale = conf.rating_scale()
    if value not in scale:
        raise exceptions.ValidationError(
            'Choose a rating from %(min)s to %(max)s.',
            code='out_of_scale',
            params={'min': scale.start, 'max': scale.stop - 1},
        )


validate_week_key = RegexValidator(
    regex=r'\A[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])\Z',
    message='Enter a week in the form YYYY-Www, e.g. 2026-W40.',
    code='invalid_week_key',
)


class RatingField(models.IntegerField):
    """An integer field that rejects anything that is not a whole number.

    IntegerField.to_python() would silently truncate 2.5 or Decimal('2.5')
    to 2, accept True as 1, and accept strings such as '1_0' or non-ASCII
    digits. Only ints, integral floats/Decimals and ASCII digit strings pass.
    """

    _INTEGER_STRING = re.compile(r'\s*[+-]?[0-9]+\s*', re.ASCII)

    def to_python(self, value):
        if value is None or value == '':
            return super().to_python(value)
        if not self._is_integral(value):
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={'value': value},
            )
        return super().to_python(value)

    def _is_integral(self, value):
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, str):
            return self._INTEGER_STRING.fullmatch(value) is not None
        if isinstance(value, numbers.Number):
            try:
                return math.isfinite(value) and value == int(value)
            except (TypeError, ValueError, OverflowError):
                return False
        return False


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='projects',
    )
    name = models.CharField(max_length=100, validators=[validate_not_blank])
    share_token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        default=generate_share_token,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def regenerate_share_token(self):
        """Replace the share token with a new, unused one; the old link stops working."""
        with transaction.atomic():
            token = generate_share_token()
            while Project.objects.filter(share_token=token).exists():
                token = generate_share_token()
            self.share_token = token
            self.save(update_fields=['share_token'])


class Submission(models.Model):
    """One anonymous weekly rating. Holds nothing that identifies a respondent."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    week_key = models.CharField(max_length=8, validators=[validate_week_key])
    workload = RatingField('My workload is manageable', validators=[validate_rating])
    clarity = RatingField('Our goals and priorities are clear', validators=[validate_rating])
    collaboration = RatingField('We work well together', validators=[validate_rating])
    progress = RatingField('I am confident we will deliver', validators=[validate_rating])

    class Meta:
        indexes = [
            models.Index(fields=['project', 'week_key'], name='pulse_sub_project_week_idx'),
        ]

    def __str__(self):
        return f'Submission for {self.project_id} in {self.week_key}'


INVITATION_LIFETIME = timedelta(days=7)


class InvitationQuerySet(models.QuerySet):
    def open(self, now=None):
        """Invitations that are neither used, revoked nor expired at ``now``."""
        now = now or timezone.now()
        return self.filter(used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now)


class Invitation(models.Model):
    """A single-use link that lets one person create a lead account (#8)."""

    token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        default=generate_share_token,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = InvitationQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.expires_at is None:
            self.expires_at = self.created_at + INVITATION_LIFETIME
        super().save(*args, **kwargs)

    def is_open(self, now=None):
        """Valid strictly before ``expires_at``, invalid at exactly that time."""
        now = now or timezone.now()
        return self.used_at is None and self.revoked_at is None and now < self.expires_at

    def __str__(self):
        return f'Invitation {self.pk}'
