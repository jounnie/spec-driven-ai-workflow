"""Django admin for users, projects and invitations (#16).

Privacy: ``Submission`` is deliberately not registered, and nothing here
renders ratings or per-week data. The delete confirmation pages would list
cascaded submissions (with their week keys), so they are replaced by pages
that show the project and a count only.
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.utils import model_ngettext
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.shortcuts import redirect
from django.db.models import Q
from django.template import engines
from django.template.response import TemplateResponse
from django.utils import timezone

from pulse import services
from pulse.models import Invitation, Project

BULK_DELETE_TEMPLATE = """{% extends "admin/base_site.html" %}
{% load i18n %}
{% block breadcrumbs %}
<ol class="breadcrumbs">
<li><a href="{% url 'admin:index' %}">Home</a></li>
<li><a href="{% url 'admin:pulse_project_changelist' %}">Projects</a></li>
<li aria-current="page">Delete multiple objects</li>
</ol>
{% endblock %}
{% block content %}
<p>Are you sure you want to delete {{ count }} project{{ count|pluralize }}?
All their ratings will be permanently deleted.</p>
<form method="post">{% csrf_token %}
<div>
{% for pk in pks %}<input type="hidden" name="{{ action_checkbox_name }}" value="{{ pk }}">{% endfor %}
<input type="hidden" name="action" value="delete_selected">
<input type="hidden" name="post" value="yes">
<input type="submit" value="Yes, I’m sure">
<a role="button" href="{% url 'admin:pulse_project_changelist' %}" class="button cancel-link">No, take me back</a>
</div>
</form>
{% endblock %}
"""


@admin.action(description='Delete selected projects', permissions=['delete'])
def delete_selected(modeladmin, request, queryset):
    """Bulk delete that shows only a count, then deletes through ``delete_project``."""
    count = queryset.count()
    if request.POST.get('post'):
        modeladmin.log_deletions(request, queryset)
        modeladmin.delete_queryset(request, queryset)
        modeladmin.message_user(
            request,
            f'Successfully deleted {count} {model_ngettext(modeladmin.opts, count)}.',
            messages.SUCCESS,
        )
        return None
    context = {
        **modeladmin.admin_site.each_context(request),
        'title': 'Are you sure?',
        'opts': modeladmin.opts,
        'count': count,
        'pks': list(queryset.values_list('pk', flat=True)),
        'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
    }
    template = engines['django'].from_string(BULK_DELETE_TEMPLATE)
    return TemplateResponse(request, template, context)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'owner']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = get_user_model().objects.filter(is_active=True)
        if self.instance.pk:
            # keep the current owner selectable, so saving a project owned by a
            # deactivated lead does not fail
            users = get_user_model().objects.filter(Q(is_active=True) | Q(pk=self.instance.owner_id))
        self.fields['owner'].queryset = users.order_by('username')

    def clean_owner(self):
        owner = self.cleaned_data['owner']
        if not owner.is_active and owner.pk != self.instance.owner_id:
            raise forms.ValidationError('Choose an active user.')
        return owner


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    form = ProjectForm
    list_display = ('name', 'owner', 'created_at')
    list_select_related = ('owner',)
    search_fields = ('name',)
    ordering = ('name',)
    readonly_fields = ('created_at',)
    fields = ('name', 'owner', 'created_at')
    actions = [delete_selected]

    def get_deleted_objects(self, objs, request):
        # The stock version lists cascaded submissions with their week keys.
        objs = list(objs)
        names = [f'Project: {obj}' for obj in objs]
        return names, {'projects': len(objs)}, set(), []

    def delete_model(self, request, obj):
        services.delete_project(obj)

    def delete_queryset(self, request, queryset):
        for project in list(queryset):
            services.delete_project(project)


LAST_SUPERUSER_MESSAGE = 'The last active superuser cannot be deleted or deactivated.'


def removes_last_superuser(users):
    """True if taking ``users`` out of service leaves no active superuser.

    ``users`` is a queryset or list of the accounts being deleted or deactivated.
    """
    pks = [user.pk for user in users if user.is_superuser and user.is_active]
    if not pks:
        return False
    return not get_user_model().objects.filter(is_superuser=True, is_active=True).exclude(pk__in=pks).exists()


ADMIN_RIGHTS_MESSAGE = 'The last active superuser cannot have admin rights removed.'


def loses_last_admin_rights(user, cleaned):
    """True if the edit takes is_staff or is_superuser from the last active staff superuser."""
    was_admin = user.is_active and user.is_staff and user.is_superuser
    keeps_rights = cleaned.get('is_staff', user.is_staff) and cleaned.get('is_superuser', user.is_superuser)
    if not was_admin or keeps_rights:
        return False
    others = get_user_model().objects.filter(is_active=True, is_staff=True, is_superuser=True)
    return not others.exclude(pk=user.pk).exists()


class LeadChangeForm(UserChangeForm):
    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and 'is_active' in self.changed_data and not cleaned.get('is_active', True):
            if removes_last_superuser([self.instance]):
                raise forms.ValidationError(LAST_SUPERUSER_MESSAGE)
        if self.instance.pk and loses_last_admin_rights(self.instance, cleaned):
            raise forms.ValidationError(ADMIN_RIGHTS_MESSAGE)
        return cleaned


@admin.action(description='Delete selected users', permissions=['delete'])
def delete_selected_users(modeladmin, request, queryset):
    """Stock bulk delete (which shows protected projects), minus the last superuser."""
    if removes_last_superuser(list(queryset)):
        modeladmin.message_user(request, LAST_SUPERUSER_MESSAGE, messages.ERROR)
        return None
    return admin.actions.delete_selected(modeladmin, request, queryset)


delete_selected_users.__name__ = 'delete_selected'


class LeadAdmin(UserAdmin):
    form = LeadChangeForm
    actions = [delete_selected_users]

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if obj is not None and removes_last_superuser([obj]):
            self.message_user(request, LAST_SUPERUSER_MESSAGE, messages.ERROR)
            return redirect('admin:auth_user_change', obj.pk)
        return super().delete_view(request, object_id, extra_context)


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), LeadAdmin)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_by', 'created_at', 'expires_at', 'status')
    list_select_related = ('created_by',)
    ordering = ('-created_at',)
    fields = ('created_by', 'created_at', 'expires_at', 'used_at', 'used_by', 'revoked_at')

    @admin.display(description='Status')
    def status(self, obj):
        return invitation_status(obj)

    def get_list_filter(self, request):
        return (InvitationStatusFilter, 'created_at')


def invitation_status(invitation, now=None):
    now = now or timezone.now()
    if invitation.revoked_at is not None:
        return 'revoked'
    if invitation.used_at is not None:
        return 'used'
    if invitation.expires_at <= now:
        return 'expired'
    return 'open'


class InvitationStatusFilter(admin.SimpleListFilter):
    title = 'status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [('open', 'open'), ('used', 'used'), ('expired', 'expired'), ('revoked', 'revoked')]

    def queryset(self, request, queryset):
        now = timezone.now()
        value = self.value()
        if value == 'revoked':
            return queryset.filter(revoked_at__isnull=False)
        if value == 'used':
            return queryset.filter(revoked_at__isnull=True, used_at__isnull=False)
        if value == 'expired':
            return queryset.filter(revoked_at__isnull=True, used_at__isnull=True, expires_at__lte=now)
        if value == 'open':
            return queryset.filter(revoked_at__isnull=True, used_at__isnull=True, expires_at__gt=now)
        return queryset
