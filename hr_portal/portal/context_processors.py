from django.conf import settings

from .models import Notification
from .services import acting_for, can_manage_groups, can_use_chat, get_employee, get_perms, is_manager, role_label


def portal(request):
    user = request.user
    ctx = {"COMPANY_NAME": settings.COMPANY_NAME, "COMPANY_SHORT": settings.COMPANY_SHORT_NAME}
    # Ajax requests (search, paging, filters) only need the page content - not the header / sidebar again.
    ctx["base_template"] = (
        "portal/ajax_base.html" if request.headers.get("X-Requested-With") == "fetch" else "portal/base.html"
    )
    if user.is_authenticated:
        emp = get_employee(user)
        # What the sidebar shows under the name: the designation (not "Employee" / "Super Admin").
        designation = emp.designation.name if emp and emp.designation else ""
        ctx.update(
            {
                "is_manager": is_manager(user),
                "my_perms": sorted(get_perms(user)),
                "my_employee": emp,
                "can_groups": can_use_chat(user),
                "can_manage_groups": can_manage_groups(user),
                "acting_for": acting_for(user),
                "my_role": role_label(user),
                "my_title": designation or ("" if role_label(user) in ("Employee", "Super Admin") else role_label(user)),
                "display_name": user.get_full_name() or user.username,
                "unread_notifications": Notification.objects.filter(recipient=emp, is_read=False).count() if emp else 0,
            }
        )
    return ctx
