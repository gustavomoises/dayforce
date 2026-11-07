"""Langfuse's own `@observe`, re-exported so services never import Langfuse."""

from langfuse import observe as traced

__all__ = ["traced"]
