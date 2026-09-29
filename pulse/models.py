import secrets

from django.conf import settings
from django.core import exceptions
from django.core.validators import RegexValidator
from django.db import models

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
    regex=r'\A\d{4}-W(0[1-9]|[1-4]\d|5[0-3])\Z',
    message='Enter a week in the form YYYY-Www, e.g. 2026-W40.',
    code='invalid_week_key',
)


class RatingField(models.IntegerField):
    """An integer field that rejects non-integral values such as 2.5 or True.

    IntegerField.to_python() would silently truncate 2.5 to 2.
    """

    def to_python(self, value):
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={'value': value},
            )
        return super().to_python(value)


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
