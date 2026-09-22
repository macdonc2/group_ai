"""Neo4j adapter implementing the KnowledgeGraph port."""

import json
from datetime import datetime
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from agent_system.domain.entities import KnowledgeNode, KnowledgeNodeType
from agent_system.domain.ports import KnowledgeGraphPort
from agent_system.domain.value_objects import (
    KnowledgeNodeId,
    Relationship,
    RelationType,
    Suggestion,
    UserId,
)


class Neo4jAdapter(KnowledgeGraphPort):
    """Neo4j implementation of the KnowledgeGraph port."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        """Initialize the Neo4j adapter.
        
        Args:
            uri: Neo4j connection URI (e.g., bolt://localhost:7687)
            user: Neo4j username
            password: Neo4j password
            database: Database name
        """
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Establish connection to Neo4j."""
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )

    async def close(self) -> None:
        """Close the Neo4j connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None

    @property
    def driver(self) -> AsyncDriver:
        """Get the Neo4j driver, raising if not connected."""
        if not self._driver:
            raise RuntimeError("Neo4j adapter not connected. Call connect() first.")
        return self._driver

    async def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Create a new node in the graph."""
        query = """
        CREATE (n:KnowledgeNode {
            id: $id,
            node_type: $node_type,
            label: $label,
            properties_json: $properties_json,
            created_at: $created_at,
            updated_at: $updated_at
        })
        RETURN n
        """
        async with self.driver.session(database=self._database) as session:
            await session.run(
                query,
                id=str(node.id),
                node_type=node.node_type.value,
                label=node.label,
                properties_json=json.dumps(node.properties),  # Serialize dict to JSON string
                created_at=node.created_at.isoformat(),
                updated_at=node.updated_at.isoformat(),
            )
        return node

    async def get_node(self, node_id: KnowledgeNodeId) -> KnowledgeNode | None:
        """Get a node by ID."""
        query = """
        MATCH (n:KnowledgeNode {id: $id})
        RETURN n
        """
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, id=str(node_id))
            record = await result.single()
            if record:
                return self._record_to_node(record["n"])
        return None

    async def update_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Update an existing node."""
        query = """
        MATCH (n:KnowledgeNode {id: $id})
        SET n.label = $label,
            n.properties_json = $properties_json,
            n.updated_at = $updated_at
        RETURN n
        """
        async with self.driver.session(database=self._database) as session:
            await session.run(
                query,
                id=str(node.id),
                label=node.label,
                properties_json=json.dumps(node.properties),
                updated_at=node.updated_at.isoformat(),
            )
        return node

    async def delete_node(self, node_id: KnowledgeNodeId) -> bool:
        """Delete a node and its relationships."""
        query = """
        MATCH (n:KnowledgeNode {id: $id})
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, id=str(node_id))
            record = await result.single()
            return record["deleted"] > 0 if record else False

    async def create_relationship(
        self,
        source_id: KnowledgeNodeId,
        target_id: KnowledgeNodeId,
        relation_type: RelationType,
        properties: dict[str, Any] | None = None,
    ) -> Relationship:
        """Create a relationship between two nodes."""
        props = properties or {}
        query = f"""
        MATCH (a:KnowledgeNode {{id: $source_id}})
        MATCH (b:KnowledgeNode {{id: $target_id}})
        CREATE (a)-[r:{relation_type.value} {{
            weight: $weight,
            properties_json: $properties_json,
            created_at: $created_at
        }}]->(b)
        RETURN r
        """
        now = datetime.utcnow()
        async with self.driver.session(database=self._database) as session:
            await session.run(
                query,
                source_id=str(source_id),
                target_id=str(target_id),
                weight=props.get("weight", 1.0),
                properties_json=json.dumps(props),
                created_at=now.isoformat(),
            )
        
        return Relationship(
            relation_type=relation_type,
            source_id=str(source_id),
            target_id=str(target_id),
            weight=props.get("weight", 1.0),
            properties=props,
            created_at=now,
        )

    async def get_relationships(
        self,
        node_id: KnowledgeNodeId,
        relation_type: RelationType | None = None,
        direction: str = "both",
    ) -> list[Relationship]:
        """Get relationships for a node."""
        if direction == "outgoing":
            pattern = "(a)-[r]->(b)"
            match_clause = "a.id = $id"
        elif direction == "incoming":
            pattern = "(a)<-[r]-(b)"
            match_clause = "a.id = $id"
        else:
            pattern = "(a)-[r]-(b)"
            match_clause = "a.id = $id"

        type_filter = f"AND type(r) = '{relation_type.value}'" if relation_type else ""
        
        query = f"""
        MATCH {pattern}
        WHERE {match_clause} {type_filter}
        RETURN type(r) as rel_type, a.id as source, b.id as target, 
               r.weight as weight, r.properties_json as properties_json, r.created_at as created_at
        """
        
        relationships = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, id=str(node_id))
            async for record in result:
                props_json = record.get("properties_json")
                if isinstance(props_json, str):
                    props = json.loads(props_json)
                elif props_json:
                    props = props_json
                else:
                    props = {}
                
                relationships.append(
                    Relationship(
                        relation_type=RelationType(record["rel_type"]),
                        source_id=record["source"],
                        target_id=record["target"],
                        weight=record["weight"] or 1.0,
                        properties=props,
                        created_at=datetime.fromisoformat(record["created_at"]) if record["created_at"] else datetime.utcnow(),
                    )
                )
        return relationships

    async def find_nodes(
        self,
        node_type: KnowledgeNodeType | None = None,
        properties: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[KnowledgeNode]:
        """Find nodes matching criteria."""
        where_clauses = []
        params: dict[str, Any] = {"limit": limit}
        
        if node_type:
            where_clauses.append("n.node_type = $node_type")
            params["node_type"] = node_type.value
        
        if properties:
            for key, value in properties.items():
                param_name = f"prop_{key}"
                where_clauses.append(f"n.properties.{key} = ${param_name}")
                params[param_name] = value
        
        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        query = f"""
        MATCH (n:KnowledgeNode)
        {where_clause}
        RETURN n
        LIMIT $limit
        """
        
        nodes = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, **params)
            async for record in result:
                nodes.append(self._record_to_node(record["n"]))
        return nodes

    async def get_user_nodes(
        self,
        user_id: UserId,
        node_type: KnowledgeNodeType | None = None,
    ) -> list[KnowledgeNode]:
        """Get all nodes associated with a user."""
        type_filter = f"AND n.node_type = '{node_type.value}'" if node_type else ""
        
        # Match user node by user_id property (not id), then traverse to connected nodes
        query = f"""
        MATCH (u:KnowledgeNode {{node_type: 'user', user_id: $user_id}})-[*1..3]-(n:KnowledgeNode)
        WHERE n.id <> u.id {type_filter}
        RETURN DISTINCT n
        UNION
        MATCH (u:KnowledgeNode {{node_type: 'user', user_id: $user_id}})
        RETURN u as n
        """
        
        nodes = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id))
            async for record in result:
                nodes.append(self._record_to_node(record["n"]))
        return nodes

    async def find_connected_nodes(
        self,
        node_id: KnowledgeNodeId,
        relation_type: RelationType | None = None,
        max_depth: int = 1,
    ) -> list[KnowledgeNode]:
        """Find nodes connected to a given node."""
        rel_filter = f":{relation_type.value}" if relation_type else ""
        
        query = f"""
        MATCH (a:KnowledgeNode {{id: $id}})-[r{rel_filter}*1..{max_depth}]-(b:KnowledgeNode)
        WHERE b.id <> $id
        RETURN DISTINCT b
        """
        
        nodes = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, id=str(node_id))
            async for record in result:
                nodes.append(self._record_to_node(record["b"]))
        return nodes

    async def get_suggestions_for_user(
        self,
        user_id: UserId,
        limit: int = 5,
    ) -> list[Suggestion]:
        """Get suggestions for a user based on their knowledge graph."""
        # Find topics and intents the user has interacted with
        query = """
        MATCH (u:KnowledgeNode {node_type: 'user'})-[:HAS_INTENT|INTERESTED_IN*1..2]-(topic:KnowledgeNode)
        WHERE u.properties.user_id = $user_id
        AND topic.node_type IN ['topic', 'intent']
        WITH topic, count(*) as relevance
        ORDER BY relevance DESC
        LIMIT $limit
        RETURN topic.label as title, topic.properties as props, relevance
        """
        
        suggestions = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), limit=limit)
            async for record in result:
                props = record["props"] or {}
                suggestions.append(
                    Suggestion(
                        title=record["title"],
                        description=props.get("description", "Related to your interests"),
                        relevance_score=min(record["relevance"] / 10.0, 1.0),
                        based_on=[],
                        action_type="explore_topic",
                    )
                )
        return suggestions

    async def record_interaction(
        self,
        user_id: UserId,
        conversation_id: str,
        summary: str,
        intents: list[str],
        entities: list[str],
        tools_used: list[str],
        user_label: str | None = None,
    ) -> KnowledgeNode:
        """Record an interaction in the knowledge graph.
        
        Uses MERGE for topics/entities so the same topic across conversations
        is a single node, enabling relationship discovery.
        """
        # Create interaction node
        interaction_node = KnowledgeNode.create_interaction_node(
            summary=summary,
            conversation_id=conversation_id,
        )
        await self.create_node(interaction_node)
        
        # Ensure user node exists
        user_node_id = KnowledgeNodeId.generate()
        user_id_str = str(user_id)
        display_label = user_label or user_id_str
        now = datetime.utcnow().isoformat()
        
        user_query = """
        MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        ON CREATE SET u.id = $id, u.label = $label,
                      u.created_at = $now, u.updated_at = $now
        SET u.label = $label, u.updated_at = $now
        RETURN u.id as id
        """
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                user_query,
                id=str(user_node_id),
                label=display_label,
                user_id=user_id_str,
                now=now,
            )
            record = await result.single()
            if record:
                user_node_id = KnowledgeNodeId.from_string(record["id"])
        
        # Connect interaction to user
        await self.create_relationship(
            user_node_id,
            interaction_node.id,
            RelationType.FOLLOWED_BY,
        )
        
        # Create and connect intent nodes (use MERGE to connect across conversations)
        for intent in intents:
            intent_query = """
            MERGE (i:KnowledgeNode {node_type: 'topic', label: $label, user_id: $user_id})
            ON CREATE SET i.id = $id, i.created_at = $now, i.updated_at = $now,
                          i.properties_json = $props
            ON MATCH SET i.updated_at = $now
            RETURN i.id as id
            """
            intent_id = str(KnowledgeNodeId.generate())
            async with self.driver.session(database=self._database) as session:
                result = await session.run(
                    intent_query,
                    id=intent_id,
                    label=intent,
                    user_id=str(user_id),
                    now=now,
                    props=json.dumps({"description": f"Intent: {intent}"}),
                )
                record = await result.single()
                if record:
                    intent_id = record["id"]
            
            await self._create_relationship_by_id(
                str(interaction_node.id), intent_id, RelationType.HAS_INTENT
            )
        
        # Create and connect entity nodes using MERGE (same entity = same node)
        entity_ids = []
        for entity in entities:
            entity_query = """
            MERGE (e:KnowledgeNode {node_type: 'topic', label: $label, user_id: $user_id})
            ON CREATE SET e.id = $id, e.created_at = $now, e.updated_at = $now,
                          e.properties_json = $props
            ON MATCH SET e.updated_at = $now
            RETURN e.id as id
            """
            entity_id = str(KnowledgeNodeId.generate())
            async with self.driver.session(database=self._database) as session:
                result = await session.run(
                    entity_query,
                    id=entity_id,
                    label=entity,
                    user_id=str(user_id),
                    now=now,
                    props=json.dumps({}),
                )
                record = await result.single()
                if record:
                    entity_id = record["id"]
                    entity_ids.append((entity, entity_id))
            
            # Connect entity to interaction
            await self._create_relationship_by_id(
                str(interaction_node.id), entity_id, RelationType.MENTIONED_IN
            )
            
            # Connect user to entity (INTERESTED_IN) 
            await self._create_relationship_by_id(
                str(user_node_id), entity_id, RelationType.INTERESTED_IN
            )
        
        # Create relationships between entities mentioned together
        # This builds the topic-to-topic relationships
        if len(entity_ids) > 1:
            for i, (entity1, id1) in enumerate(entity_ids):
                for entity2, id2 in entity_ids[i+1:]:
                    # Create RELATES_TO between co-mentioned entities
                    await self._create_relationship_by_id(
                        id1, id2, RelationType.RELATES_TO
                    )
        
        # Create and connect tool nodes (use MERGE)
        for tool in tools_used:
            tool_query = """
            MERGE (t:KnowledgeNode {node_type: 'tool', label: $label})
            ON CREATE SET t.id = $id, t.created_at = $now, t.updated_at = $now,
                          t.properties_json = $props
            ON MATCH SET t.updated_at = $now
            RETURN t.id as id
            """
            tool_id = str(KnowledgeNodeId.generate())
            async with self.driver.session(database=self._database) as session:
                result = await session.run(
                    tool_query,
                    id=tool_id,
                    label=tool,
                    now=now,
                    props=json.dumps({"tool_name": tool}),
                )
                record = await result.single()
                if record:
                    tool_id = record["id"]
            
            await self._create_relationship_by_id(
                str(interaction_node.id), tool_id, RelationType.USED_TOOL
            )
        
        return interaction_node

    async def _create_relationship_by_id(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a relationship between nodes by their string IDs.
        
        Uses MERGE to avoid duplicate relationships.
        """
        props = properties or {}
        now = datetime.utcnow().isoformat()
        
        query = f"""
        MATCH (a:KnowledgeNode {{id: $source_id}})
        MATCH (b:KnowledgeNode {{id: $target_id}})
        MERGE (a)-[r:{relation_type.value}]->(b)
        ON CREATE SET r.weight = $weight, r.properties_json = $properties_json,
                      r.created_at = $created_at
        """
        
        async with self.driver.session(database=self._database) as session:
            await session.run(
                query,
                source_id=source_id,
                target_id=target_id,
                weight=props.get("weight", 1.0),
                properties_json=json.dumps(props),
                created_at=now,
            )

    async def clear_user_graph(self, user_id: UserId) -> int:
        """Clear all nodes and relationships for a user."""
        query = """
        MATCH (u:KnowledgeNode {node_type: 'user', user_id: $user_id})-[*]-(n:KnowledgeNode)
        DETACH DELETE n
        WITH count(n) as deleted
        MATCH (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        DETACH DELETE u
        RETURN deleted + 1 as total_deleted
        """
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id))
            record = await result.single()
            return record["total_deleted"] if record else 0

    async def update_user_label(self, user_id: UserId, label: str) -> bool:
        """Update the label of a user node."""
        query = """
        MATCH (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        SET u.label = $label
        RETURN u.id as id
        """
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                label=label,
            )
            record = await result.single()
            return record is not None

    def _record_to_node(self, record: dict[str, Any]) -> KnowledgeNode:
        """Convert a Neo4j record to a KnowledgeNode."""
        # Handle both old 'properties' and new 'properties_json' field names
        props_json = record.get("properties_json") or record.get("properties")
        if isinstance(props_json, str):
            properties = json.loads(props_json)
        elif props_json:
            properties = props_json
        else:
            properties = {}
        
        return KnowledgeNode(
            id=KnowledgeNodeId.from_string(record["id"]),
            node_type=KnowledgeNodeType(record["node_type"]),
            label=record["label"],
            properties=properties,
            created_at=datetime.fromisoformat(record["created_at"]) if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"]) if record.get("updated_at") else datetime.utcnow(),
        )

    # ============ Vector/Embedding Operations ============

    async def ensure_vector_index(self, dimensions: int = 1536) -> bool:
        """Ensure the vector index exists for semantic search."""
        # Check if index already exists
        check_query = """
        SHOW INDEXES
        YIELD name, type
        WHERE name = 'message_embeddings'
        RETURN count(*) as exists
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(check_query)
            record = await result.single()
            
            if record and record["exists"] > 0:
                return True
        
        # Create vector index if it doesn't exist
        # Neo4j 5.11+ supports vector indexes
        create_query = f"""
        CREATE VECTOR INDEX message_embeddings IF NOT EXISTS
        FOR (m:MessageEmbedding) ON (m.embedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {dimensions},
            `vector.similarity_function`: 'cosine'
        }}}}
        """
        
        try:
            async with self.driver.session(database=self._database) as session:
                await session.run(create_query)
            return True
        except Exception as e:
            # Log error but don't fail - index might already exist with different config
            print(f"Warning: Could not create vector index: {e}")
            return False

    async def store_message_embedding(
        self,
        user_id: UserId,
        conversation_id: str,
        message_id: str,
        content: str,
        role: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a message with its embedding for semantic search.
        
        Also connects the message to the user node for better graph traversal.
        """
        import uuid
        
        node_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        meta = metadata or {}
        
        # Create message embedding and connect to user in one transaction
        query = """
        // Create the message embedding
        CREATE (m:MessageEmbedding {
            id: $id,
            user_id: $user_id,
            conversation_id: $conversation_id,
            message_id: $message_id,
            content: $content,
            role: $role,
            embedding: $embedding,
            metadata_json: $metadata_json,
            created_at: $created_at
        })
        
        // Connect to user if exists
        WITH m
        OPTIONAL MATCH (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        FOREACH (_ IN CASE WHEN u IS NOT NULL THEN [1] ELSE [] END |
            CREATE (u)-[:DISCUSSED]->(m)
        )
        
        RETURN m.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                id=node_id,
                user_id=str(user_id),
                conversation_id=conversation_id,
                message_id=message_id,
                content=content[:5000],  # Limit content length
                role=role,
                embedding=embedding,
                metadata_json=json.dumps(meta),
                created_at=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def semantic_search(
        self,
        user_id: UserId,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search for semantically similar messages using vector similarity."""
        # Use Neo4j's vector search
        query = """
        CALL db.index.vector.queryNodes('message_embeddings', $limit, $embedding)
        YIELD node, score
        WHERE node.user_id = $user_id AND score >= $min_score
        RETURN 
            node.id as id,
            node.content as content,
            node.role as role,
            node.conversation_id as conversation_id,
            node.message_id as message_id,
            node.metadata_json as metadata_json,
            node.created_at as created_at,
            score
        ORDER BY score DESC
        """
        
        results = []
        try:
            async with self.driver.session(database=self._database) as session:
                result = await session.run(
                    query,
                    embedding=query_embedding,
                    user_id=str(user_id),
                    limit=limit * 2,  # Fetch more to filter by user
                    min_score=min_score,
                )
                async for record in result:
                    meta = {}
                    if record.get("metadata_json"):
                        try:
                            meta = json.loads(record["metadata_json"])
                        except Exception:
                            pass
                    
                    results.append({
                        "id": record["id"],
                        "content": record["content"],
                        "role": record["role"],
                        "conversation_id": record["conversation_id"],
                        "message_id": record["message_id"],
                        "metadata": meta,
                        "created_at": record["created_at"],
                        "score": record["score"],
                    })
        except Exception as e:
            # Fall back to brute force if vector index doesn't exist
            print(f"Vector index query failed: {e}. Falling back to brute force.")
            results = await self._brute_force_semantic_search(
                user_id, query_embedding, limit, min_score
            )
        
        return results[:limit]

    async def _brute_force_semantic_search(
        self,
        user_id: UserId,
        query_embedding: list[float],
        limit: int,
        min_score: float,
    ) -> list[dict[str, Any]]:
        """Fallback brute force semantic search without vector index."""
        import math
        
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)
        
        query = """
        MATCH (m:MessageEmbedding {user_id: $user_id})
        RETURN 
            m.id as id,
            m.content as content,
            m.role as role,
            m.conversation_id as conversation_id,
            m.message_id as message_id,
            m.metadata_json as metadata_json,
            m.created_at as created_at,
            m.embedding as embedding
        """
        
        results = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id))
            async for record in result:
                embedding = record.get("embedding")
                if embedding:
                    score = cosine_similarity(query_embedding, embedding)
                    if score >= min_score:
                        meta = {}
                        if record.get("metadata_json"):
                            try:
                                meta = json.loads(record["metadata_json"])
                            except Exception:
                                pass
                        
                        results.append({
                            "id": record["id"],
                            "content": record["content"],
                            "role": record["role"],
                            "conversation_id": record["conversation_id"],
                            "message_id": record["message_id"],
                            "metadata": meta,
                            "created_at": record["created_at"],
                            "score": score,
                        })
        
        # Sort by score and limit
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ============ Group Knowledge Operations ============

    async def store_group_message_embedding(
        self,
        group_id: str,
        conversation_id: str,
        message_id: str,
        user_id: str,
        user_email: str,
        content: str,
        role: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a group message with its embedding for group semantic search.
        
        Args:
            group_id: The group identifier
            conversation_id: The conversation identifier
            message_id: Unique message identifier
            user_id: The user who sent the message
            user_email: User's email for display
            content: The message content
            role: Message role (user/assistant)
            embedding: The embedding vector
            metadata: Optional additional metadata
            
        Returns:
            The node ID of the stored message
        """
        import uuid
        
        node_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        meta = metadata or {}
        
        query = """
        CREATE (m:GroupMessageEmbedding {
            id: $id,
            group_id: $group_id,
            conversation_id: $conversation_id,
            message_id: $message_id,
            user_id: $user_id,
            user_email: $user_email,
            content: $content,
            role: $role,
            embedding: $embedding,
            metadata_json: $metadata_json,
            created_at: $created_at
        })
        RETURN m.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                id=node_id,
                group_id=group_id,
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                user_email=user_email,
                content=content[:5000],
                role=role,
                embedding=embedding,
                metadata_json=json.dumps(meta),
                created_at=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def group_semantic_search(
        self,
        group_id: str,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search for semantically similar messages within a group.
        
        Args:
            group_id: The group identifier
            query_embedding: The query embedding vector
            limit: Maximum number of results
            min_score: Minimum similarity score (0-1)
            
        Returns:
            List of matching messages with scores
        """
        import math
        
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)
        
        # For groups, we do brute force search filtered by group_id
        # (Can upgrade to vector index later if needed)
        query = """
        MATCH (m:GroupMessageEmbedding {group_id: $group_id})
        RETURN 
            m.id as id,
            m.content as content,
            m.role as role,
            m.user_id as user_id,
            m.user_email as user_email,
            m.conversation_id as conversation_id,
            m.message_id as message_id,
            m.metadata_json as metadata_json,
            m.created_at as created_at,
            m.embedding as embedding
        """
        
        results = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, group_id=group_id)
            async for record in result:
                embedding = record.get("embedding")
                if embedding:
                    score = cosine_similarity(query_embedding, embedding)
                    if score >= min_score:
                        meta = {}
                        if record.get("metadata_json"):
                            try:
                                meta = json.loads(record["metadata_json"])
                            except Exception:
                                pass
                        
                        results.append({
                            "id": record["id"],
                            "content": record["content"],
                            "role": record["role"],
                            "user_id": record["user_id"],
                            "user_email": record["user_email"],
                            "conversation_id": record["conversation_id"],
                            "message_id": record["message_id"],
                            "metadata": meta,
                            "created_at": record["created_at"],
                            "score": score,
                        })
        
        # Sort by score and limit
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    async def record_group_interaction(
        self,
        group_id: str,
        user_id: str,
        conversation_id: str,
        summary: str,
        topics: list[str],
        entities: list[str],
        user_label: str | None = None,
    ) -> KnowledgeNode:
        """Record a group interaction in the knowledge graph.
        
        Creates nodes for group knowledge that can be shared across members.
        """
        # Create interaction node
        interaction_node = KnowledgeNode.create_interaction_node(
            summary=summary,
            conversation_id=conversation_id,
        )
        # Add group_id to properties
        interaction_node = KnowledgeNode(
            id=interaction_node.id,
            node_type=interaction_node.node_type,
            label=f"Group: {summary[:50]}",
            properties={**interaction_node.properties, "group_id": group_id},
            created_at=interaction_node.created_at,
            updated_at=interaction_node.updated_at,
        )
        await self.create_node(interaction_node)
        
        # Create or update group node
        group_node_id = KnowledgeNodeId.generate()
        now = datetime.utcnow().isoformat()
        
        group_query = """
        MERGE (g:KnowledgeNode {node_type: 'group', group_id: $group_id})
        ON CREATE SET g.id = $id, g.label = $label,
                      g.created_at = $now, g.updated_at = $now
        ON MATCH SET g.updated_at = $now
        RETURN g.id as id
        """
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                group_query,
                id=str(group_node_id),
                label=f"Group {group_id[:8]}",
                group_id=group_id,
                now=now,
            )
            record = await result.single()
            if record:
                group_node_id = KnowledgeNodeId.from_string(record["id"])
        
        # Connect interaction to group
        await self.create_relationship(
            group_node_id,
            interaction_node.id,
            RelationType.FOLLOWED_BY,
        )
        
        # Create topic nodes (shared across group)
        for topic in topics[:5]:
            topic_node = KnowledgeNode.create_topic_node(topic)
            await self.create_node(topic_node)
            await self.create_relationship(
                interaction_node.id,
                topic_node.id,
                RelationType.MENTIONED_IN,
            )
        
        # Create entity nodes
        for entity in entities[:5]:
            entity_node = KnowledgeNode.create_topic_node(entity)
            await self.create_node(entity_node)
            await self.create_relationship(
                interaction_node.id,
                entity_node.id,
                RelationType.MENTIONED_IN,
            )
        
        return interaction_node

    async def get_group_knowledge(
        self,
        group_id: str,
        limit: int = 50,
    ) -> list[KnowledgeNode]:
        """Get all knowledge nodes associated with a group."""
        query = """
        MATCH (g:KnowledgeNode {node_type: 'group', group_id: $group_id})-[*1..2]-(n:KnowledgeNode)
        WHERE n.id <> g.id
        RETURN DISTINCT n
        LIMIT $limit
        UNION
        MATCH (g:KnowledgeNode {node_type: 'group', group_id: $group_id})
        RETURN g as n
        """
        
        nodes = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, group_id=group_id, limit=limit)
            async for record in result:
                nodes.append(self._record_to_node(record["n"]))
        return nodes

    # ============ Social Graph Operations (Person, Pet, Location) ============

    async def store_person(
        self,
        user_id: UserId,
        name: str,
        aliases: list[str] | None = None,
        relationship_type: str | None = None,
        context_notes: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> str:
        """Store or update a person in the user's social graph.
        
        Uses MERGE by name (case-insensitive) to deduplicate.
        Creates KNOWS relationship to user.
        
        Returns:
            The node ID of the person
        """
        import uuid
        
        now = datetime.utcnow().isoformat()
        node_id = str(uuid.uuid4())
        alias_list = aliases or []
        
        # MERGE person by lowercase name within user's graph
        query = """
        // Ensure user node exists
        MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        ON CREATE SET u.id = $user_node_id, u.label = 'User', 
                      u.created_at = $now, u.updated_at = $now
        
        // MERGE person by name (case-insensitive)
        WITH u
        MERGE (p:PersonNode {user_id: $user_id, name_lower: toLower($name)})
        ON CREATE SET 
            p.id = $id,
            p.name = $name,
            p.aliases = $aliases,
            p.relationship_type = $relationship_type,
            p.context_notes = $context_notes,
            p.email = $email,
            p.phone = $phone,
            p.first_mentioned = $now,
            p.last_mentioned = $now,
            p.mention_count = 1,
            p.created_at = $now
        ON MATCH SET 
            p.last_mentioned = $now,
            p.mention_count = p.mention_count + 1,
            p.aliases = CASE WHEN size($aliases) > size(p.aliases) THEN $aliases ELSE p.aliases END,
            p.relationship_type = COALESCE($relationship_type, p.relationship_type),
            p.context_notes = COALESCE($context_notes, p.context_notes),
            p.email = COALESCE($email, p.email),
            p.phone = COALESCE($phone, p.phone)
        
        // Create KNOWS relationship
        MERGE (u)-[:KNOWS]->(p)
        
        RETURN p.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                user_node_id=str(uuid.uuid4()),
                id=node_id,
                name=name,
                aliases=alias_list,
                relationship_type=relationship_type,
                context_notes=context_notes,
                email=email,
                phone=phone,
                now=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def get_person(
        self,
        user_id: UserId,
        name: str,
    ) -> dict[str, Any] | None:
        """Get a person by name (case-insensitive) from user's social graph."""
        query = """
        MATCH (p:PersonNode {user_id: $user_id, name_lower: toLower($name)})
        RETURN p
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), name=name)
            record = await result.single()
            if record:
                return dict(record["p"])
        return None

    async def find_person_by_alias(
        self,
        user_id: UserId,
        alias: str,
    ) -> dict[str, Any] | None:
        """Find a person by alias match."""
        query = """
        MATCH (p:PersonNode {user_id: $user_id})
        WHERE toLower($alias) IN [a IN p.aliases | toLower(a)]
           OR p.name_lower = toLower($alias)
        RETURN p
        LIMIT 1
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), alias=alias)
            record = await result.single()
            if record:
                return dict(record["p"])
        return None

    async def list_known_people(
        self,
        user_id: UserId,
        relationship_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List all people in user's social graph."""
        where_clause = ""
        if relationship_type:
            where_clause = "AND p.relationship_type = $relationship_type"
        
        query = f"""
        MATCH (p:PersonNode {{user_id: $user_id}})
        WHERE p.id IS NOT NULL {where_clause}
        RETURN p
        ORDER BY p.mention_count DESC, p.last_mentioned DESC
        LIMIT $limit
        """
        
        params = {"user_id": str(user_id), "limit": limit}
        if relationship_type:
            params["relationship_type"] = relationship_type
        
        people = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, **params)
            async for record in result:
                people.append(dict(record["p"]))
        return people

    async def store_pet(
        self,
        user_id: UserId,
        name: str,
        aliases: list[str] | None = None,
        species: str | None = None,
        breed: str | None = None,
        personality: list[str] | None = None,
        food_preferences: list[str] | None = None,
        health_notes: str | None = None,
    ) -> str:
        """Store or update a pet in the user's household.
        
        Returns:
            The node ID of the pet
        """
        import uuid
        
        now = datetime.utcnow().isoformat()
        node_id = str(uuid.uuid4())
        
        query = """
        // Ensure user node exists
        MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        ON CREATE SET u.id = $user_node_id, u.label = 'User',
                      u.created_at = $now, u.updated_at = $now
        
        // MERGE pet by name
        WITH u
        MERGE (p:PetNode {user_id: $user_id, name_lower: toLower($name)})
        ON CREATE SET
            p.id = $id,
            p.name = $name,
            p.aliases = $aliases,
            p.species = $species,
            p.breed = $breed,
            p.personality = $personality,
            p.food_preferences = $food_preferences,
            p.health_notes = $health_notes,
            p.first_mentioned = $now,
            p.last_mentioned = $now,
            p.mention_count = 1,
            p.created_at = $now
        ON MATCH SET
            p.last_mentioned = $now,
            p.mention_count = p.mention_count + 1,
            p.aliases = CASE WHEN size($aliases) > size(COALESCE(p.aliases, [])) THEN $aliases ELSE p.aliases END,
            p.species = COALESCE($species, p.species),
            p.breed = COALESCE($breed, p.breed),
            p.personality = CASE WHEN size($personality) > 0 THEN 
                [x IN p.personality WHERE NOT x IN $personality] + $personality 
                ELSE p.personality END,
            p.food_preferences = CASE WHEN size($food_preferences) > 0 THEN
                [x IN p.food_preferences WHERE NOT x IN $food_preferences] + $food_preferences
                ELSE p.food_preferences END,
            p.health_notes = COALESCE($health_notes, p.health_notes)
        
        // Create OWNS relationship
        MERGE (u)-[:OWNS]->(p)
        
        RETURN p.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                user_node_id=str(uuid.uuid4()),
                id=node_id,
                name=name,
                aliases=aliases or [],
                species=species,
                breed=breed,
                personality=personality or [],
                food_preferences=food_preferences or [],
                health_notes=health_notes,
                now=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def get_pet(
        self,
        user_id: UserId,
        name: str,
    ) -> dict[str, Any] | None:
        """Get a pet by name from user's household."""
        query = """
        MATCH (p:PetNode {user_id: $user_id, name_lower: toLower($name)})
        RETURN p
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), name=name)
            record = await result.single()
            if record:
                return dict(record["p"])
        return None

    async def list_pets(
        self,
        user_id: UserId,
        species: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all pets in user's household."""
        where_clause = ""
        if species:
            where_clause = "AND toLower(p.species) = toLower($species)"
        
        query = f"""
        MATCH (p:PetNode {{user_id: $user_id}})
        WHERE p.id IS NOT NULL {where_clause}
        RETURN p
        ORDER BY p.mention_count DESC
        """
        
        params: dict[str, Any] = {"user_id": str(user_id)}
        if species:
            params["species"] = species
        
        pets = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, **params)
            async for record in result:
                pets.append(dict(record["p"]))
        return pets

    async def store_location(
        self,
        user_id: UserId,
        name: str,
        aliases: list[str] | None = None,
        location_type: str | None = None,
        address: str | None = None,
        city: str | None = None,
        neighborhood: str | None = None,
        associated_activities: list[str] | None = None,
        notes: str | None = None,
    ) -> str:
        """Store or update a location the user frequents.
        
        Returns:
            The node ID of the location
        """
        import uuid
        
        now = datetime.utcnow().isoformat()
        node_id = str(uuid.uuid4())
        
        query = """
        // Ensure user node exists
        MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        ON CREATE SET u.id = $user_node_id, u.label = 'User',
                      u.created_at = $now, u.updated_at = $now
        
        // MERGE location by name
        WITH u
        MERGE (l:LocationNode {user_id: $user_id, name_lower: toLower($name)})
        ON CREATE SET
            l.id = $id,
            l.name = $name,
            l.aliases = $aliases,
            l.location_type = $location_type,
            l.address = $address,
            l.city = $city,
            l.neighborhood = $neighborhood,
            l.associated_activities = $associated_activities,
            l.notes = $notes,
            l.first_mentioned = $now,
            l.last_mentioned = $now,
            l.mention_count = 1,
            l.created_at = $now
        ON MATCH SET
            l.last_mentioned = $now,
            l.mention_count = l.mention_count + 1,
            l.aliases = CASE WHEN size($aliases) > size(COALESCE(l.aliases, [])) THEN $aliases ELSE l.aliases END,
            l.location_type = COALESCE($location_type, l.location_type),
            l.address = COALESCE($address, l.address),
            l.city = COALESCE($city, l.city),
            l.neighborhood = COALESCE($neighborhood, l.neighborhood),
            l.associated_activities = CASE WHEN size($associated_activities) > 0 THEN
                [x IN l.associated_activities WHERE NOT x IN $associated_activities] + $associated_activities
                ELSE l.associated_activities END,
            l.notes = COALESCE($notes, l.notes)
        
        // Create FREQUENTS relationship
        MERGE (u)-[:FREQUENTS]->(l)
        
        RETURN l.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                user_node_id=str(uuid.uuid4()),
                id=node_id,
                name=name,
                aliases=aliases or [],
                location_type=location_type,
                address=address,
                city=city,
                neighborhood=neighborhood,
                associated_activities=associated_activities or [],
                notes=notes,
                now=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def get_location(
        self,
        user_id: UserId,
        name: str,
    ) -> dict[str, Any] | None:
        """Get a location by name."""
        query = """
        MATCH (l:LocationNode {user_id: $user_id, name_lower: toLower($name)})
        RETURN l
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), name=name)
            record = await result.single()
            if record:
                return dict(record["l"])
        return None

    async def list_locations(
        self,
        user_id: UserId,
        location_type: str | None = None,
        city: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all locations the user frequents."""
        where_clauses = ["l.id IS NOT NULL"]
        params: dict[str, Any] = {"user_id": str(user_id)}
        
        if location_type:
            where_clauses.append("toLower(l.location_type) = toLower($location_type)")
            params["location_type"] = location_type
        if city:
            where_clauses.append("toLower(l.city) = toLower($city)")
            params["city"] = city
        
        where_clause = " AND ".join(where_clauses)
        
        query = f"""
        MATCH (l:LocationNode {{user_id: $user_id}})
        WHERE {where_clause}
        RETURN l
        ORDER BY l.mention_count DESC
        """
        
        locations = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, **params)
            async for record in result:
                locations.append(dict(record["l"]))
        return locations

    async def link_entities(
        self,
        user_id: UserId,
        source_type: str,
        source_name: str,
        target_type: str,
        target_name: str,
        relationship: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Create a relationship between two entities.
        
        Args:
            user_id: The user's ID
            source_type: Type of source entity (person, pet, location)
            source_name: Name of source entity
            target_type: Type of target entity
            target_name: Name of target entity
            relationship: Relationship type (e.g., WORKS_AT, FRIEND_OF)
            properties: Optional relationship properties
            
        Returns:
            True if relationship was created
        """
        now = datetime.utcnow().isoformat()
        props = properties or {}
        
        # Map type to label
        type_to_label = {
            "person": "PersonNode",
            "pet": "PetNode",
            "location": "LocationNode",
            "user": "KnowledgeNode",
        }
        
        source_label = type_to_label.get(source_type.lower(), "KnowledgeNode")
        target_label = type_to_label.get(target_type.lower(), "KnowledgeNode")
        
        # Build dynamic query based on source/target types
        if source_type.lower() == "user":
            source_match = f"(s:{source_label} {{node_type: 'user', user_id: $user_id}})"
        else:
            source_match = f"(s:{source_label} {{user_id: $user_id, name_lower: toLower($source_name)}})"
        
        if target_type.lower() == "user":
            target_match = f"(t:{target_label} {{node_type: 'user', user_id: $user_id}})"
        else:
            target_match = f"(t:{target_label} {{user_id: $user_id, name_lower: toLower($target_name)}})"
        
        # Use dynamic relationship type (sanitize it first)
        rel_type = relationship.upper().replace(" ", "_").replace("-", "_")
        
        query = f"""
        MATCH {source_match}
        MATCH {target_match}
        MERGE (s)-[r:{rel_type}]->(t)
        ON CREATE SET r.created_at = $now, r.properties_json = $properties_json
        RETURN s.id as source_id, t.id as target_id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                source_name=source_name,
                target_name=target_name,
                now=now,
                properties_json=json.dumps(props),
            )
            record = await result.single()
            return record is not None

    async def resolve_entity_by_alias(
        self,
        user_id: UserId,
        alias: str,
    ) -> dict[str, Any] | None:
        """Resolve an alias or reference to an entity.
        
        Searches across Person, Pet, and Location nodes.
        
        Returns:
            Dict with 'type' and entity data, or None if not found
        """
        # Search persons first
        person = await self.find_person_by_alias(user_id, alias)
        if person:
            return {"type": "person", "entity": person}
        
        # Search pets
        query = """
        MATCH (p:PetNode {user_id: $user_id})
        WHERE toLower($alias) IN [a IN p.aliases | toLower(a)]
           OR p.name_lower = toLower($alias)
        RETURN p, 'pet' as type
        LIMIT 1
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), alias=alias)
            record = await result.single()
            if record:
                return {"type": "pet", "entity": dict(record["p"])}
        
        # Search locations
        query = """
        MATCH (l:LocationNode {user_id: $user_id})
        WHERE toLower($alias) IN [a IN l.aliases | toLower(a)]
           OR l.name_lower = toLower($alias)
           OR toLower(l.name) CONTAINS toLower($alias)
        RETURN l, 'location' as type
        LIMIT 1
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), alias=alias)
            record = await result.single()
            if record:
                return {"type": "location", "entity": dict(record["l"])}
        
        return None

    async def get_entity_relationships(
        self,
        user_id: UserId,
        entity_type: str,
        entity_name: str,
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Get all relationships for an entity (for contextual suggestions).
        
        Args:
            user_id: The user's ID
            entity_type: Type of entity (person, pet, location)
            entity_name: Name of the entity
            max_depth: Maximum relationship depth to traverse
            
        Returns:
            List of related entities with relationship info
        """
        type_to_label = {
            "person": "PersonNode",
            "pet": "PetNode",
            "location": "LocationNode",
        }
        
        label = type_to_label.get(entity_type.lower(), "PersonNode")
        
        query = f"""
        MATCH (e:{label} {{user_id: $user_id, name_lower: toLower($name)}})
        MATCH (e)-[r*1..{max_depth}]-(related)
        WHERE related <> e
        WITH related, 
             [rel in r | type(rel)] as rel_types,
             length(r) as depth
        RETURN 
            labels(related)[0] as related_type,
            related.name as related_name,
            related.id as related_id,
            rel_types,
            depth
        ORDER BY depth ASC
        LIMIT 50
        """
        
        relationships = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                name=entity_name,
            )
            async for record in result:
                relationships.append({
                    "related_type": record["related_type"],
                    "related_name": record["related_name"],
                    "related_id": record["related_id"],
                    "relationship_path": record["rel_types"],
                    "depth": record["depth"],
                })
        return relationships

    # ============ Temporal Operations ============

    async def ensure_temporal_index(self) -> bool:
        """Ensure indexes exist for temporal queries."""
        queries = [
            "CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:MessageEmbedding) ON (m.created_at)",
            "CREATE INDEX group_message_timestamp IF NOT EXISTS FOR (m:GroupMessageEmbedding) ON (m.created_at)",
            "CREATE INDEX person_mentioned IF NOT EXISTS FOR (p:PersonNode) ON (p.last_mentioned)",
            "CREATE INDEX pet_mentioned IF NOT EXISTS FOR (p:PetNode) ON (p.last_mentioned)",
            "CREATE INDEX location_mentioned IF NOT EXISTS FOR (l:LocationNode) ON (l.last_mentioned)",
        ]
        
        try:
            async with self.driver.session(database=self._database) as session:
                for query in queries:
                    try:
                        await session.run(query)
                    except Exception:
                        pass  # Index might already exist
            return True
        except Exception as e:
            print(f"Warning: Could not create temporal indexes: {e}")
            return False

    async def recall_from_period(
        self,
        user_id: UserId,
        start_date: datetime,
        end_date: datetime,
        topic: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Recall messages from a specific time period.
        
        Args:
            user_id: The user's ID
            start_date: Start of period
            end_date: End of period
            topic: Optional topic filter (searches content)
            limit: Maximum results
            
        Returns:
            List of messages from the period
        """
        topic_filter = ""
        if topic:
            topic_filter = "AND toLower(m.content) CONTAINS toLower($topic)"
        
        query = f"""
        MATCH (m:MessageEmbedding {{user_id: $user_id}})
        WHERE m.created_at >= $start_date AND m.created_at <= $end_date
        {topic_filter}
        RETURN 
            m.id as id,
            m.content as content,
            m.role as role,
            m.conversation_id as conversation_id,
            m.created_at as created_at
        ORDER BY m.created_at DESC
        LIMIT $limit
        """
        
        params: dict[str, Any] = {
            "user_id": str(user_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "limit": limit,
        }
        if topic:
            params["topic"] = topic
        
        results = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, **params)
            async for record in result:
                results.append({
                    "id": record["id"],
                    "content": record["content"],
                    "role": record["role"],
                    "conversation_id": record["conversation_id"],
                    "created_at": record["created_at"],
                })
        return results

    async def recall_about_topic(
        self,
        user_id: UserId,
        topic: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for mentions of a topic in user's conversation history.
        
        Searches both MessageEmbedding content and KnowledgeNode labels
        to find relevant information about an entity or topic.
        
        Args:
            user_id: The user's ID
            topic: The topic/entity name to search for
            limit: Maximum results
            
        Returns:
            List of relevant text snippets mentioning the topic
        """
        results = []
        
        # Search MessageEmbedding for topic mentions
        # CRITICAL: Prioritize USER messages over assistant messages!
        # User messages contain defining info like "Zane is my dog"
        # Assistant messages are just responses that mention the name
        message_query = """
        MATCH (m:MessageEmbedding {user_id: $user_id})
        WHERE toLower(m.content) CONTAINS toLower($topic)
        RETURN 
            m.content as content,
            m.role as role,
            m.created_at as created_at,
            'message' as source_type,
            CASE WHEN m.role = 'user' THEN 0 ELSE 1 END as priority
        ORDER BY priority ASC, m.created_at DESC
        LIMIT $limit
        """
        
        # Also search KnowledgeNode labels
        # CRITICAL: Prioritize nodes that DEFINE what the entity IS
        # e.g., "User has a dog named Zane" should come before "Zane's birthday"
        # Priority 0: topic/fact nodes with defining keywords (dog, pet, cat, spouse, etc.)
        # Priority 1: other topic/fact nodes
        # Priority 2: interaction nodes
        knowledge_query = """
        MATCH (k:KnowledgeNode)
        WHERE (k.user_id = $user_id OR k.user_id IS NULL)
          AND toLower(k.label) CONTAINS toLower($topic)
        WITH k, toLower(k.label) as lbl
        WITH k, lbl,
             CASE 
                 WHEN k.node_type IN ['topic', 'fact', 'entity', 'preference', 'personal'] 
                      AND (lbl CONTAINS 'dog' OR lbl CONTAINS 'pet' OR lbl CONTAINS 'cat' 
                           OR lbl CONTAINS 'spouse' OR lbl CONTAINS 'wife' OR lbl CONTAINS 'husband'
                           OR lbl CONTAINS 'friend' OR lbl CONTAINS 'brother' OR lbl CONTAINS 'sister'
                           OR lbl CONTAINS 'son' OR lbl CONTAINS 'daughter' OR lbl CONTAINS 'parent'
                           OR lbl CONTAINS 'is my' OR lbl CONTAINS 'is a' OR lbl CONTAINS 'is the')
                 THEN 0
                 WHEN k.node_type IN ['topic', 'fact', 'entity', 'preference', 'personal'] THEN 1
                 ELSE 2
             END as priority
        RETURN 
            k.label as content,
            k.node_type as role,
            k.created_at as created_at,
            'knowledge' as source_type,
            priority
        ORDER BY priority ASC, k.created_at DESC
        LIMIT $limit
        """
        
        params = {
            "user_id": str(user_id),
            "topic": topic,
            "limit": limit,
        }
        
        async with self.driver.session(database=self._database) as session:
            # Get message results
            result = await session.run(message_query, **params)
            async for record in result:
                results.append({
                    "content": record["content"],
                    "role": record["role"],
                    "created_at": record["created_at"],
                    "source_type": record["source_type"],
                })
            
            # Get knowledge node results - INSERT AT FRONT since they have defining info
            knowledge_results = []
            result = await session.run(knowledge_query, **params)
            async for record in result:
                # Avoid duplicates
                content = record["content"]
                if not any(r["content"] == content for r in results):
                    knowledge_results.append({
                        "content": content,
                        "role": record["role"],
                        "created_at": record["created_at"],
                        "source_type": record["source_type"],
                    })
        
        # Prioritize knowledge nodes (topic/fact) over messages
        # Knowledge nodes contain defining info like "Zane is my dog"
        combined = knowledge_results + results
        return combined[:limit]

    # ============ Preference Operations ============

    async def store_preference(
        self,
        user_id: UserId,
        category: str,
        value: str,
        sentiment: float = 0.5,
        subcategory: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        """Store or update a user preference.
        
        Args:
            user_id: The user's ID
            category: Preference category (food, activities, schedule, etc.)
            value: The preference value
            sentiment: Sentiment score (-1 to 1, negative = dislike)
            subcategory: Optional subcategory
            conversation_id: Optional source conversation
            
        Returns:
            The preference node ID
        """
        import uuid
        
        now = datetime.utcnow().isoformat()
        node_id = str(uuid.uuid4())
        
        query = """
        MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        ON CREATE SET u.id = $user_node_id, u.label = 'User',
                      u.created_at = $now, u.updated_at = $now
        
        WITH u
        MERGE (p:PreferenceNode {
            user_id: $user_id, 
            category_lower: toLower($category),
            value_lower: toLower($value)
        })
        ON CREATE SET
            p.id = $id,
            p.category = $category,
            p.subcategory = $subcategory,
            p.value = $value,
            p.sentiment = $sentiment,
            p.mention_count = 1,
            p.confidence = 0.5,
            p.first_mentioned = $now,
            p.last_mentioned = $now,
            p.source_conversations = CASE WHEN $conversation_id IS NOT NULL 
                THEN [$conversation_id] ELSE [] END,
            p.created_at = $now
        ON MATCH SET
            p.last_mentioned = $now,
            p.mention_count = p.mention_count + 1,
            p.sentiment = (p.sentiment * p.mention_count + $sentiment) / (p.mention_count + 1),
            p.confidence = CASE WHEN p.mention_count > 3 THEN 0.8 
                WHEN p.mention_count > 1 THEN 0.6 ELSE 0.5 END,
            p.source_conversations = CASE WHEN $conversation_id IS NOT NULL 
                AND NOT $conversation_id IN p.source_conversations
                THEN p.source_conversations + [$conversation_id]
                ELSE p.source_conversations END
        
        MERGE (u)-[:HAS_PREFERENCE]->(p)
        
        RETURN p.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                user_node_id=str(uuid.uuid4()),
                id=node_id,
                category=category,
                subcategory=subcategory,
                value=value,
                sentiment=sentiment,
                conversation_id=conversation_id,
                now=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def get_user_preferences(
        self,
        user_id: UserId,
        category: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Get user preferences, optionally filtered by category.
        
        Args:
            user_id: The user's ID
            category: Optional category filter
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of preference dicts
        """
        where_clauses = ["p.confidence >= $min_confidence"]
        params: dict[str, Any] = {
            "user_id": str(user_id),
            "min_confidence": min_confidence,
        }
        
        if category:
            where_clauses.append("toLower(p.category) = toLower($category)")
            params["category"] = category
        
        where_clause = " AND ".join(where_clauses)
        
        query = f"""
        MATCH (p:PreferenceNode {{user_id: $user_id}})
        WHERE {where_clause}
        RETURN p
        ORDER BY p.confidence DESC, p.mention_count DESC
        """
        
        prefs = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, **params)
            async for record in result:
                prefs.append(dict(record["p"]))
        return prefs

    # ============ Thread Operations ============

    async def store_thread(
        self,
        user_id: UserId,
        name: str,
        description: str | None = None,
        conversation_id: str | None = None,
        topics: list[str] | None = None,
    ) -> str:
        """Store or update a cross-conversation thread.
        
        Returns:
            The thread node ID
        """
        import uuid
        
        now = datetime.utcnow().isoformat()
        node_id = str(uuid.uuid4())
        
        query = """
        MERGE (u:KnowledgeNode {node_type: 'user', user_id: $user_id})
        ON CREATE SET u.id = $user_node_id, u.label = 'User',
                      u.created_at = $now, u.updated_at = $now
        
        WITH u
        MERGE (t:ThreadNode {user_id: $user_id, name_lower: toLower($name)})
        ON CREATE SET
            t.id = $id,
            t.name = $name,
            t.description = $description,
            t.status = 'active',
            t.conversation_ids = CASE WHEN $conversation_id IS NOT NULL 
                THEN [$conversation_id] ELSE [] END,
            t.related_topics = $topics,
            t.created_at = $now,
            t.last_updated = $now
        ON MATCH SET
            t.last_updated = $now,
            t.description = COALESCE($description, t.description),
            t.conversation_ids = CASE WHEN $conversation_id IS NOT NULL
                AND NOT $conversation_id IN t.conversation_ids
                THEN t.conversation_ids + [$conversation_id]
                ELSE t.conversation_ids END,
            t.related_topics = CASE WHEN size($topics) > 0 THEN
                [x IN t.related_topics WHERE NOT x IN $topics] + $topics
                ELSE t.related_topics END
        
        MERGE (u)-[:HAS_THREAD]->(t)
        
        RETURN t.id as id
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                user_node_id=str(uuid.uuid4()),
                id=node_id,
                name=name,
                description=description,
                conversation_id=conversation_id,
                topics=topics or [],
                now=now,
            )
            record = await result.single()
            return record["id"] if record else node_id

    async def get_thread_history(
        self,
        user_id: UserId,
        thread_name: str,
    ) -> dict[str, Any] | None:
        """Get full thread history with all linked conversations."""
        query = """
        MATCH (t:ThreadNode {user_id: $user_id, name_lower: toLower($name)})
        RETURN t
        """
        
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, user_id=str(user_id), name=thread_name)
            record = await result.single()
            if record:
                return dict(record["t"])
        return None

    # ============ Contextual Suggestions ============

    async def get_contextual_suggestions(
        self,
        user_id: UserId,
        mentioned_entities: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get contextual suggestions based on mentioned entities.
        
        Traverses graph 2 hops from mentioned entities to find related context.
        
        Args:
            user_id: The user's ID
            mentioned_entities: Names of entities mentioned in current message
            limit: Maximum suggestions
            
        Returns:
            List of suggestion dicts with relevance scores
        """
        if not mentioned_entities:
            return []
        
        query = """
        // Find matching entities
        UNWIND $entities as entity_name
        OPTIONAL MATCH (p:PersonNode {user_id: $user_id})
        WHERE p.name_lower = toLower(entity_name) OR toLower(entity_name) IN [a IN p.aliases | toLower(a)]
        OPTIONAL MATCH (pet:PetNode {user_id: $user_id})
        WHERE pet.name_lower = toLower(entity_name) OR toLower(entity_name) IN [a IN pet.aliases | toLower(a)]
        OPTIONAL MATCH (l:LocationNode {user_id: $user_id})
        WHERE l.name_lower = toLower(entity_name) OR toLower(entity_name) IN [a IN l.aliases | toLower(a)]
        
        // Collect found entities
        WITH collect(p) + collect(pet) + collect(l) as found_entities
        UNWIND found_entities as e
        
        // Traverse 2 hops to find related entities
        MATCH (e)-[r*1..2]-(related)
        WHERE related <> e AND NOT related:KnowledgeNode
        
        // Score by recency and relationship strength
        WITH related, 
             count(*) as connection_strength,
             max(related.last_mentioned) as recency
        ORDER BY connection_strength DESC, recency DESC
        LIMIT $limit
        
        RETURN 
            labels(related)[0] as type,
            related.name as name,
            related.id as id,
            connection_strength,
            recency
        """
        
        suggestions = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user_id=str(user_id),
                entities=mentioned_entities,
                limit=limit,
            )
            async for record in result:
                suggestions.append({
                    "type": record["type"],
                    "name": record["name"],
                    "id": record["id"],
                    "relevance": min(record["connection_strength"] / 5.0, 1.0),
                    "recency": record["recency"],
                })
        return suggestions

    # ============ Interest Overlap (Group Features) ============

    async def get_shared_interests(
        self,
        user1_id: UserId,
        user2_id: UserId,
    ) -> list[str]:
        """Find shared interests between two users.
        
        Returns:
            List of shared topic/interest names
        """
        query = """
        MATCH (u1:KnowledgeNode {node_type: 'user', user_id: $user1_id})-[:INTERESTED_IN]->(t:KnowledgeNode)
              <-[:INTERESTED_IN]-(u2:KnowledgeNode {node_type: 'user', user_id: $user2_id})
        RETURN t.label as shared_interest
        """
        
        interests = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(
                query,
                user1_id=str(user1_id),
                user2_id=str(user2_id),
            )
            async for record in result:
                interests.append(record["shared_interest"])
        return interests

    async def get_group_consensus(
        self,
        group_id: str,
        topic: str,
    ) -> dict[str, Any]:
        """Get group consensus on a topic.
        
        Analyzes what group members have said about a topic.
        
        Returns:
            Dict with consensus info (opinions, agreement level)
        """
        query = """
        MATCH (m:GroupMessageEmbedding {group_id: $group_id})
        WHERE toLower(m.content) CONTAINS toLower($topic)
        RETURN 
            m.user_email as user,
            m.content as content,
            m.created_at as timestamp
        ORDER BY m.created_at DESC
        LIMIT 20
        """
        
        mentions = []
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, group_id=group_id, topic=topic)
            async for record in result:
                mentions.append({
                    "user": record["user"],
                    "content": record["content"],
                    "timestamp": record["timestamp"],
                })
        
        return {
            "topic": topic,
            "mention_count": len(mentions),
            "mentions": mentions,
            "users_involved": list(set(m["user"] for m in mentions)),
        }
