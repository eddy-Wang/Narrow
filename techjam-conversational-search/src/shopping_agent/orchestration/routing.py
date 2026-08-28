from shopping_agent.domain.state import ShoppingState


def route_after_filter(state: ShoppingState) -> str:
    return "relax_and_backfill" if len(state.get("filtered_candidates", [])) < 30 else "rerank"
