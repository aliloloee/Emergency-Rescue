from rest_framework import permissions


class AnyOnPost_AuthOnGet(permissions.BasePermission) :
    """Allow all users to send post request to this url, but only authenticated user to send get request."""

    def has_permission(self, request, view):
        if request.user.is_anonymous and request.method == 'POST' :
            return True
        
        if  request.user.is_authenticated and request.method == 'GET' :
            return True

        return False