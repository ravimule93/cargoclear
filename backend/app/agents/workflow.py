"""ADK Workflow DAG definition.

Defines the google-adk Workflow graph that orchestrates the CargoClear
assessment pipeline. The Workflow wraps the same service functions that
the orchestrator.py dispatches to — keeping logic in services, not agents.

ADK version: google-adk >= 0.3.0 (PyPI).

NOTE: The exact ADK 2.x API surface (google.adk.Workflow, @node decorator,
RetryConfig) should be verified at install time. The Tech Plan v4.0 §2.2
specifies google-adk >= 2.6.3, but the PyPI package name and import path
may differ. See requirements.txt comment.

Phase 2: Uncomment and verify against the installed ADK version.
Skeleton: Module-level stub; workflow is not invoked.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# ---- Phase 2: uncomment after verifying ADK API ----
# from google.adk import Agent, Workflow
# from google.adk.workflow import RetryConfig
# from app.agents.extraction import extraction_agent
# from app.agents.grounding import grounding_agent
#
# root_agent = Workflow(
#     name="cargoclear_orchestrator",
#     edges=[
#         ("START", preprocess_node, extraction_agent),
#         (extraction_agent, discrepancy_node, grounding_agent),
#         (grounding_agent, synthesize_node, audit_node),
#     ],
#     retry_config=RetryConfig(max_attempts=3),  # For JSON-schema failures
# )
# ---------------------------------------------------

# Skeleton placeholder
root_agent = None

logger.debug("adk_workflow_module_loaded", note="ADK Workflow is stubbed until Phase 2.")
