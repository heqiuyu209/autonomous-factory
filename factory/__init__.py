"""Autonomous Software Venture Factory - V1 core.

Implements the SOFTWARE FACTORY layer of the blueprint:

    Planner/Coder/Reviewer/QA  ->  a task-graph driven pipeline
    that turns a PRD + task graph into a working, verified application.

The key architectural invariant (blueprint §20):
    The agent that writes code is NOT the one that verifies it.
"""

__version__ = "0.1.0"
