from automation.actions.create_reminder import execute as create_reminder


# "add_activity" ("Add CRM Activity") used to be registered here too, but
# its output (activity_type "Automation" in ai_activity) has no visible
# effect anywhere in the UI anymore - there's no standalone Activity Log
# panel, and timeline_manager.get_customer_timeline() deliberately
# excludes "Automation" entries from the merged Customer Timeline. Rather
# than keep offering an action that silently does nothing observable, it
# was removed from the rule builder and unregistered here.
ACTION_REGISTRY = {

    "create_reminder": create_reminder,

}