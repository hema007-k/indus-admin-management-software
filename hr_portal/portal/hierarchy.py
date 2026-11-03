"""Staff hierarchy used to order the Employee table (taken from the company staff list).

Managing Director first, then Directors, Associate Directors (+ senior staff / FAEs) - these are "top management"
and are listed first, whatever the department. Everybody else is listed department by department, and inside a
department the senior designation comes first. Drivers / Field Supervisors / House keeping are kept as separate
groups at the end.
"""

TOP_RANK = 3          # designation.rank <= 3  ->  top management, listed first

# (text that must appear in the designation name, rank)  - first match wins, so keep specific names first
DESIGNATION_RANKS = [
    ("managing director", 1),
    ("associate director", 3),
    ("assistant director", 4),
    ("director", 2),                      # Director, Director - Admin
    ("mentor", 3),
    ("fae", 3),                           # FAE, EIA coordinator and FAE
    ("manager", 5),                       # Technical Quality Manager, Administrative Manager
    ("senior project officer", 6),
    ("senior accounts officer", 6),
    ("project officer", 8),
    ("accounts officer", 8),
    ("system administrator", 8),
    ("field supervisor", 9),              # Field Supervisor, Driver / Field Supervisor
    ("office assistant", 10),
    ("house keeping", 10),
    ("housekeeping", 10),
    ("driver", 10),
    ("watchman", 10),
]
DEFAULT_RANK = 50


def rank_for(designation_name):
    name = (designation_name or "").strip().lower()
    for text, rank in DESIGNATION_RANKS:
        if text in name:
            return rank
    return DEFAULT_RANK


# department order = order of the staff list; the "support" groups go to the end
DEPARTMENT_ORDER = [
    "instrumentation", "seabed surveys", "lab team", "eia", "modelling", "modeling", "gis", "ship navigation",
    "system administration", "admin", "accounts", "software development",
]
SEPARATE_LAST = ["drivers", "field supervisors", "house keeping"]


def department_sort_order(name):
    n = (name or "").strip().lower()
    if n in SEPARATE_LAST:
        return 900 + SEPARATE_LAST.index(n)
    if n in DEPARTMENT_ORDER:
        return 10 + DEPARTMENT_ORDER.index(n) * 10
    return 500
