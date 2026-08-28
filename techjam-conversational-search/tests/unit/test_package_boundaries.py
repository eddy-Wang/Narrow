from shopping_agent.application.service import ShoppingAgent
from shopping_agent.domain.schemas import Constraint
from shopping_agent.orchestration.nodes import ShoppingGraphNodes
from shopping_agent.ranking.interfaces import CandidateRanker
from shopping_agent.retrieval.interfaces import SemanticRetriever
from shopping_agent.understanding.state_patch import StatePatch


def test_public_component_boundaries_are_importable() -> None:
    assert ShoppingAgent is not None
    assert ShoppingGraphNodes is not None
    assert CandidateRanker is not None
    assert SemanticRetriever is not None
    assert StatePatch(constraints=[Constraint(field="color", value="black")])


def test_legacy_imports_still_resolve_to_new_components() -> None:
    from shopping_agent.agent import ShoppingAgent as LegacyShoppingAgent
    from shopping_agent.schemas import Constraint as LegacyConstraint
    from shopping_agent.semantic_state import StatePatch as LegacyStatePatch

    assert LegacyShoppingAgent is ShoppingAgent
    assert LegacyConstraint is Constraint
    assert LegacyStatePatch is StatePatch
