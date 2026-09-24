"""Autonomous Software Venture Factory - V2 core.

Implements the PLANNING + SOFTWARE FACTORY layers of the blueprint:

    PM / Architect  ->  Planner/Coder/Reviewer/QA  ->  a task-graph driven
    pipeline that turns a problem statement into a working, verified
    application (PRD -> task graph -> code).

The key architectural invariant (blueprint §20):
    The agent that writes code is NOT the one that verifies it.
"""

__version__ = "2.0.0"
