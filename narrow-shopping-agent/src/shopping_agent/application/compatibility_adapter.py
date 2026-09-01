from shopping_agent.application.service import ShoppingAgent


class CompatibilityAgent(ShoppingAgent):
    """Thin name-boundary for the organizer's reset/respond contract."""


__all__ = ["CompatibilityAgent"]
