"""Create and tear down a synthetic user whose memories are known exactly.

Everything is scoped by user_id (SQL rows cascade from the user; Neo4j nodes
carry `user_id`), so eval users can run against a shared database and are
removed afterwards.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from agent_system.evals.schema import EvalCase

logger = logging.getLogger(__name__)

EVAL_EMAIL_DOMAIN = "evals.invalid"


@dataclass
class SeededUser:
    user: Any  # domain User
    seeded_message_ids: dict[str, str] = field(default_factory=dict)  # content -> MessageEmbedding id
    seed_conversation_id: str = ""


async def seed_user(case: EvalCase, run_id: str, database: Any, kg: Any, embedder: Any) -> SeededUser:
    from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository
    from agent_system.domain.entities import User

    user = User.create(email=f"eval-{run_id[:8]}-{uuid.uuid4().hex[:8]}@{EVAL_EMAIL_DOMAIN}", hashed_password="!")
    user = user.update_preferences(auto_plan=case.seed.auto_plan)
    async with database.session() as session:
        await SQLAlchemyUserRepository(session).save(user)
        await session.commit()

    seeded = SeededUser(user=user, seed_conversation_id=str(uuid.uuid4()))
    if kg is None:
        return seeded

    s = case.seed
    for p in s.people:
        await kg.store_person(user_id=user.id, name=p.name, aliases=p.aliases,
                              relationship_type=p.relationship_type, context_notes=p.context_notes)
    for p in s.pets:
        await kg.store_pet(user_id=user.id, name=p.name, aliases=p.aliases, species=p.species, breed=p.breed,
                           personality=p.personality, food_preferences=p.food_preferences)
    for loc in s.locations:
        await kg.store_location(user_id=user.id, name=loc.name, location_type=loc.location_type,
                                city=loc.city, neighborhood=loc.neighborhood)
    for pref in s.preferences:
        await kg.store_preference(user_id=user.id, category=pref.category, value=pref.value, sentiment=pref.sentiment)
    for link in s.links:
        await kg.link_entities(user_id=user.id, source_type=link.source_type, source_name=link.source_name,
                               target_type=link.target_type, target_name=link.target_name,
                               relationship=link.relationship)

    if s.messages and embedder is not None:
        vectors = await embedder.embed_batch([m.content for m in s.messages])
        for m, vec in zip(s.messages, vectors, strict=True):
            node_id = await kg.store_message_embedding(
                user_id=user.id, conversation_id=seeded.seed_conversation_id, message_id=str(uuid.uuid4()),
                content=m.content, role=m.role, embedding=vec.embedding, metadata={"seeded": True},
            )
            seeded.seeded_message_ids[m.content] = node_id
            await _backdate(kg, node_id, datetime.utcnow() - timedelta(days=m.days_ago))
    return seeded


async def _backdate(kg: Any, node_id: str, when: datetime) -> None:
    async with kg.driver.session(database=kg._database) as session:
        await session.run("MATCH (m:MessageEmbedding {id: $id}) SET m.created_at = $ts", id=node_id, ts=when.isoformat())


async def teardown_user(seeded: SeededUser, database: Any, kg: Any) -> None:
    from agent_system.adapters.outbound.persistence import SQLAlchemyUserRepository

    uid = str(seeded.user.id)
    if kg is not None:
        try:
            async with kg.driver.session(database=kg._database) as session:
                await session.run("MATCH (n {user_id: $uid}) DETACH DELETE n", uid=uid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j teardown failed for %s: %s", uid, exc)
    try:
        async with database.session() as session:
            await SQLAlchemyUserRepository(session).delete(seeded.user.id)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQL teardown failed for %s: %s", uid, exc)


async def snapshot_entities(kg: Any, user_id: Any) -> dict[str, list[dict[str, Any]]]:
    """Social-graph state for entity-resolution scoring."""
    if kg is None:
        return {"person": [], "pet": [], "location": []}
    people = await kg.list_known_people(user_id)
    pets = await kg.list_pets(user_id)
    locations = await kg.list_locations(user_id)
    return {"person": people or [], "pet": pets or [], "location": locations or []}
