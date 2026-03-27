"""
Transitional compatibility (Phase E).

Canonical Lambda entrypoints: ``lambdas.<function>.handler`` (CDK handler strings
use that dotted path). The ``src.handlers.*`` modules re-export those modules
for older imports; remove when no longer referenced.
"""
