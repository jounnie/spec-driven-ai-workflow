from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Project, Submission


class RegistrationForm(UserCreationForm):
    """Username, password and confirmation. Reused by the invitation flow (#8)."""

    class Meta:
        model = get_user_model()
        fields = ('username',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].help_text = ''
        self.fields['password2'].help_text = ''
        self.fields['password1'].label = 'Password'
        self.fields['password2'].label = 'Password confirmation'
        for name in ('password1', 'password2'):
            self.fields[name].widget = forms.PasswordInput(attrs={'autocomplete': 'new-password'})


class ProjectForm(forms.ModelForm):
    """One field, the project name; surrounding spaces are stripped by the field."""

    class Meta:
        model = Project
        fields = ('name',)
        labels = {'name': 'Project name'}
        error_messages = {
            'name': {
                'required': 'Enter a project name.',
                'max_length': 'Use at most 100 characters.',
            },
        }


RATING_FIELDS = ('workload', 'clarity', 'collaboration', 'progress')


class SubmissionForm:
    """The respondent's four ratings, validated by ``Submission.full_clean()``.

    Only the four rating fields are read from ``data``; the project and the
    week come from the caller, never from the request. Values are passed on
    as sent, so the model's strict integer check (#4) decides what is valid.
    """

    def __init__(self, project, week_key, data=None):
        self.data = data
        self.errors = {}
        self.instance = Submission(
            project=project,
            week_key=week_key,
            **{name: (data.get(name, '') if data is not None else None) for name in RATING_FIELDS},
        )

    def is_valid(self):
        try:
            self.instance.full_clean()
        except ValidationError as error:
            self.errors = {name: True for name in RATING_FIELDS if name in error.error_dict}
            # Anything else (project, week) is a bug, not a respondent error.
            if set(error.error_dict) - set(RATING_FIELDS):
                raise
            return False
        return True

    def save(self):
        self.instance.save()
        return self.instance
