"""Seed a local demo user with a small synthetic knowledge graph for the graph explorer.

Local development only: writes to the database and Neo4j from .env.

    python scripts/seed_graph_demo.py                 # prints a generated password
    GRAPH_DEMO_PASSWORD=... python scripts/seed_graph_demo.py

A second user is seeded too, sharing a tool node with the first, so you can
confirm one user's explorer never shows the other's data.
"""

import asyncio
import os
import secrets

from agent_system.adapters.inbound.api.auth import hash_password
from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
from agent_system.composition_root.container import get_container, shutdown_container
from agent_system.domain.entities import User

DEMO_EMAIL = "graph-demo@example.com"
OTHER_EMAIL = "graph-other@example.com"


async def ensure_user(container, email: str, password: str) -> User:
    async with container.database.session() as session:
        repo = SQLAlchemyUserRepository(session)
        user = await repo.get_by_email(email)
        if user is None:
            user = User.create(email=email, hashed_password=hash_password(password)).verify()
            await repo.save(user)
            await session.commit()
        return user


async def main() -> None:
    password = os.environ.get("GRAPH_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    container = await get_container()
    kg = container.knowledge_graph_adapter
    try:
        demo = await ensure_user(container, DEMO_EMAIL, password)
        other = await ensure_user(container, OTHER_EMAIL, secrets.token_urlsafe(16))
        for user in (demo, other):
            await kg.clear_user_graph(user.id)

        uid = demo.id
        await kg.store_person(uid, "Maya Okafor", relationship_type="sibling", context_notes="Lives in Austin, climbs on weekends")
        await kg.store_person(uid, "Dev Patel", relationship_type="colleague", context_notes="Works on the data platform team")
        await kg.store_person(uid, "June Alvarez", relationship_type="friend")
        await kg.store_pet(uid, "Biscuit", species="dog", breed="corgi", personality=["stubborn", "food-motivated"])
        await kg.store_pet(uid, "Miso", species="cat")
        await kg.store_location(uid, "Crux Climbing Gym", location_type="gym", city="Austin")
        await kg.store_location(uid, "Blue Door Coffee", location_type="cafe", city="Houston")
        await kg.store_location(uid, "Northwind Office", location_type="office", city="Houston")
        await kg.store_preference(uid, "food", "oat milk lattes", sentiment=0.9)
        for src, tgt_type, tgt, rel in [
            ("Maya Okafor", "location", "Crux Climbing Gym", "FREQUENTS"),
            ("June Alvarez", "location", "Blue Door Coffee", "FREQUENTS"),
            ("Dev Patel", "location", "Northwind Office", "WORKS_AT"),
            ("Maya Okafor", "pet", "Biscuit", "DOG_SITS"),  # free-form type, outside RelationType
        ]:
            await kg.link_entities(uid, "person", src, tgt_type, tgt, rel)
        await kg.link_entities(uid, "user", "", "location", "Northwind Office", "WORKS_AT")
        await kg.record_interaction(uid, "demo-c1", "Planned a climbing weekend with Maya", ["plan a trip"],
                                    ["rock climbing", "Big Bend trip"], ["web_search"], user_label=DEMO_EMAIL)
        await kg.record_interaction(uid, "demo-c2", "Debugged consumer lag for the Kafka migration", ["debug"],
                                    ["Kafka migration", "consumer lag"], ["web_search"], user_label=DEMO_EMAIL)
        await kg.record_interaction(uid, "demo-c3", "Compared sourdough starters", ["compare options"],
                                    ["sourdough baking"], [], user_label=DEMO_EMAIL)

        await kg.store_person(other.id, "Secret Contact", relationship_type="client")
        await kg.record_interaction(other.id, "other-c1", "Confidential acquisition research", ["research"],
                                    ["Project Falcon"], ["web_search"], user_label=OTHER_EMAIL)

        nodes, edges = await kg.get_user_subgraph(uid)
        leaked = [n["label"] for n in nodes if n["label"] in ("Secret Contact", "Project Falcon", OTHER_EMAIL)
                  or "Confidential" in n["label"]]
        print(f"seeded {DEMO_EMAIL}: {len(nodes)} nodes, {len(edges)} edges; other-user nodes visible: {leaked or 'none'}")
        if not os.environ.get("GRAPH_DEMO_PASSWORD"):
            print(f"password (only set when the user is first created): {password}")
    finally:
        await shutdown_container()


if __name__ == "__main__":
    asyncio.run(main())
