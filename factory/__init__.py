"""Autonomous Software Venture Factory - V3 core.

Implements the MARKET + PLANNING + SOFTWARE FACTORY layers of the blueprint:

    Market Scout  ->  PM / Architect  ->  Planner/Coder/Reviewer/QA  ->  a
    pipeline that turns internet signals into opportunity candidates and a
    problem statement into a working, verified application
    (scout -> PRD -> task graph -> code).

The key architectural invariant (blueprint §20):
    The agent that writes code is NOT the one that verifies it.
"""

__version__ = "5.0.0"
