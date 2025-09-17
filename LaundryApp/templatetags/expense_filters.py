from django import template

register = template.Library()

@register.filter
def is_selected(category_id, selected_id):
    return str(category_id) == selected_id