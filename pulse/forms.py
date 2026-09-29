from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Project


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
