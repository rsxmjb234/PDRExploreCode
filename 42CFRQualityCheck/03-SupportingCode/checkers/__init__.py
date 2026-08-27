"""
checkers/ — Modular 42 CFR signal detection modules.

Each module exposes a check() function with a consistent interface:
    check(root, ns) -> dict

Where root is an ElementTree root and ns is the CDA namespace string.
Exception: check_facility_name takes a string instead of XML.
"""
