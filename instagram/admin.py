"""Instagram app — Admin configuration."""
from django.contrib import admin
from .models import InstagramAccount, InstagramAccountUser


class InstagramAccountUserInline(admin.TabularInline):
    model = InstagramAccountUser
    extra = 0
    readonly_fields = ('connected_at',)


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    list_display = ('username', 'ig_user_id', 'is_token_valid', 'webhook_subscribed', 'created_at')
    list_filter = ('webhook_subscribed', 'created_at')
    search_fields = ('username', 'ig_user_id')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [InstagramAccountUserInline]

    def is_token_valid(self, obj):
        return obj.is_token_valid
    is_token_valid.boolean = True
    is_token_valid.short_description = 'Token Valid'


@admin.register(InstagramAccountUser)
class InstagramAccountUserAdmin(admin.ModelAdmin):
    list_display = ('user', 'instagram_account', 'is_active', 'is_owner', 'connected_at')
    list_filter = ('is_active', 'is_owner')
    search_fields = ('user__email', 'instagram_account__username')
