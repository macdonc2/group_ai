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
            MERGE (i:KnowledgeNode {node_type: 'topic', label: $label})
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
            MERGE (e:KnowledgeNode {node_type: 'topic', label: $label})
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
