from django.contrib import admin
from profiles.models import Profile

# Register your models here.
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin) :
    list_display = ('related_user', 'type', )

    @admin.display(description='user')
    def related_user(self, obj) :
        return f'{obj.user}'