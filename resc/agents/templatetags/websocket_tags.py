import re
from django import template
from django.template.base import TemplateSyntaxError
from django.urls import Resolver404
from resc.utils import all_websocket_urlpatterns

register = template.Library()
kwarg_re = re.compile(r"(?:(\w+)=)?(.+)")


def ws_reverse(route_name, args=None, kwargs=None, current_app=None):
    """
    Custom reverse function to find WebSocket routes.
    """
    for route in all_websocket_urlpatterns:
        if route.name == route_name:
            # This is where we generate the WebSocket URL.
            # Similar to how Django's reverse resolves args and kwargs for HTTP URLs.
            path = route.pattern.regex.pattern

            # Strip the leading '^' and trailing '\Z' or '$'
            path = re.sub(r'^\^', '', path)  # Remove starting '^'
            path = re.sub(r'\\Z$', '', path)  # Remove '\Z' if present
            path = re.sub(r'\$$', '', path)   # Remove '$' if present

            # If there are arguments, substitute them in the WebSocket path.
            if args:
                path = path.format(*args)
            if kwargs:
                for key, value in kwargs.items():
                    path = path.replace(f"(?P<{key}>\\w+)", value)

            return path

    raise Resolver404(f"No route matches the name '{route_name}'")


class WebSocketURLNode(template.Node):
    def __init__(self, route_name, args, kwargs, asvar=None):
        self.route_name = route_name
        self.args = args
        self.kwargs = kwargs
        self.asvar = asvar

    def render(self, context):
        from django.urls import NoReverseMatch, reverse

        # Resolve the route_name, args, and kwargs with context
        route_name = self.route_name.resolve(context)
        args = [arg.resolve(context) for arg in self.args]
        kwargs = {key: val.resolve(context) for key, val in self.kwargs.items()}

        try:
            current_app = context.request.current_app
        except AttributeError:
            try:
                current_app = context.request.resolver_match.namespace
            except AttributeError:
                current_app = None

        try:
            ws_url = ws_reverse(route_name, args=args, kwargs=kwargs, current_app=current_app)
        except NoReverseMatch:
            if self.asvar is None:
                raise

        # Optionally assign to a template variable if 'as' is used
        if self.asvar:
            context[self.asvar] = ws_url
            return ''
        else:
            return ws_url

@register.tag
def ws_url(parser, token):
    """
    Return a WebSocket URL matching the given route with its parameters.

    This works similarly to the {% url %} tag but generates WebSocket URLs.

    Example usage:
        {% ws_url 'my_websocket_route' arg1 arg2 %}
        or
        {% ws_url 'my_websocket_route' name1=value1 name2=value2 %}
        or
        {% ws_url 'my_websocket_route' as websocket_url %}
    """
    bits = token.split_contents()

    if len(bits) < 2:
        raise TemplateSyntaxError(
            "'%s' tag requires at least one argument: a WebSocket route name." % bits[0]
        )

    # First argument is the WebSocket route name
    route_name = parser.compile_filter(bits[1])

    args = []
    kwargs = {}
    asvar = None

    # Handle remaining arguments (positional, keyword, or 'as')
    bits = bits[2:]
    if len(bits) >= 2 and bits[-2] == "as":
        asvar = bits[-1]
        bits = bits[:-2]

    for bit in bits:
        match = kwarg_re.match(bit)
        if not match:
            raise TemplateSyntaxError("Malformed arguments to ws_url tag.")
        name, value = match.groups()
        if name:
            kwargs[name] = parser.compile_filter(value)
        else:
            args.append(parser.compile_filter(value))

    return WebSocketURLNode(route_name, args, kwargs, asvar)
