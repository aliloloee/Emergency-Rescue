from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


admin.site.index_title = _('ADMIN')
admin.site.site_header = _('Emergency Rescue Admin Panel')
admin.site.site_title = _('Rescue')

schema_view = get_schema_view(
    openapi.Info(
        title="Emergency-Resuce Swagger",
        default_version='1.0.0',
        description="Rest API Document",
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('account/', include('accounts.urls', namespace='accounts')),
    path('agent/', include('agents.urls', namespace='agent')),
]


# Swagger and Open-API
urlpatterns += [
    path('swagger.json/', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('docs/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]


if settings.DEBUG :
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)