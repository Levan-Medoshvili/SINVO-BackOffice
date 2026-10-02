from django import forms
from .models import EmployeeAccess, AccessGroup


class EmployeeAccessForm(forms.ModelForm):
    class Meta:
        model = EmployeeAccess
        fields = "__all__"
    def clean(self):
        data = super().clean()
        company = data.get("company")
        if company:
            if data.get("branches") is not None and data["branches"].exclude(company=company, kind="branch").exists():
                self.add_error("branches", "Choose branches from this employee's company only.")
            if data.get("groups") is not None and data["groups"].exclude(company=company).exists():
                self.add_error("groups", "Choose groups from this employee's company only.")
        return data


class AccessGroupForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(queryset=EmployeeAccess.objects.select_related("user", "company"), required=False)
    class Meta:
        model = AccessGroup
        fields = ["company", "name", "permissions", "members"]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and not self.instance._state.adding:
            self.fields["members"].initial = self.instance.members.all()
    def clean(self):
        data = super().clean()
        company = data.get("company")
        if company and data.get("members") is not None and data["members"].exclude(company=company).exists():
            self.add_error("members", "Members must belong to the group's company.")
        return data
    def _save_m2m(self):
        super()._save_m2m()
        self.instance.members.set(self.cleaned_data["members"])
