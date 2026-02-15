"""Tools available to the agent for various capabilities."""

import asyncio
import urllib.parse
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard result from a tool execution."""

    success: bool
    data: Any
    message: str


# ============ Web Search Tool ============

async def web_search(query: str, num_results: int = 5) -> ToolResult:
    """Search the web using DuckDuckGo text search.
    
    This performs actual web searches, not just instant answers.
    
    Args:
        query: The search query
        num_results: Number of results to return (max 10)
        
    Returns:
        ToolResult with search results
    """
    try:
        from ddgs import DDGS
        
        # Run in thread pool since DDGS is synchronous
        def do_search():
            with DDGS() as ddgs:
                # Use text search for actual web results
                results = list(ddgs.text(query, max_results=min(num_results, 10)))
                return results
        
        # Run synchronous search in thread pool
        results = await asyncio.get_event_loop().run_in_executor(None, do_search)
        
        if not results:
            return ToolResult(
                success=True,
                data=[],
                message=f"No results found for '{query}'.",
            )
        
        # Format results consistently
        formatted_results = []
        for r in results:
            formatted_results.append({
                "title": r.get("title", ""),
                "url": r.get("href", r.get("link", "")),
                "snippet": r.get("body", r.get("snippet", "")),
            })
        
        return ToolResult(
            success=True,
            data=formatted_results,
            message=f"Found {len(formatted_results)} results for '{query}'",
        )
        
    except ImportError:
        # Fallback to instant answer API if ddgs not installed
        return await _web_search_instant_answer(query, num_results)
    except Exception as e:
        # Try fallback on any error
        try:
            return await _web_search_instant_answer(query, num_results)
        except Exception:
            return ToolResult(
                success=False,
                data=None,
                message=f"Search unavailable: {str(e)}. I can still help discuss this topic.",
            )


async def _web_search_instant_answer(query: str, num_results: int = 5) -> ToolResult:
    """Fallback: Search using DuckDuckGo's Instant Answer API.
    
    This is a fallback for when the full search library isn't available.
    Only works for factual queries.
    """
    try:
        encoded_query = urllib.parse.quote(query)
        api_url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                api_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
                timeout=10.0,
                follow_redirects=True,
            )
            
            if response.status_code != 200:
                return ToolResult(
                    success=False,
                    data=None,
                    message=f"Web search temporarily unavailable (status {response.status_code}).",
                )
            
            data = response.json()
            results = []
            
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", query),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("Abstract", ""),
                })
            
            for topic in data.get("RelatedTopics", [])[:num_results - len(results)]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("Text", "")[:80],
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                    })
            
            if not results:
                return ToolResult(
                    success=True,
                    data=[],
                    message=f"No instant results found for '{query}'.",
                )
            
            return ToolResult(
                success=True,
                data=results,
                message=f"Found {len(results)} results for '{query}'",
            )
            
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Search unavailable: {str(e)}.",
        )


# ============ User Management Tools ============

async def get_user_profile(
    user_id: str,
    user_repository: Any,
) -> ToolResult:
    """Get the current user's profile and preferences.
    
    Args:
        user_id: The user's ID
        user_repository: Repository for user data
        
    Returns:
        ToolResult with user profile
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        user = await user_repository.get(UserId.from_string(user_id))
        if not user:
            return ToolResult(
                success=False,
                data=None,
                message="User not found",
            )
        
        profile = {
            "email": user.email,
            "preferences": {
                "default_model": user.preferences.default_model,
                "temperature": user.preferences.temperature,
                "auto_plan": user.preferences.auto_plan,
                "verbose_responses": user.preferences.verbose_responses,
                "preferred_tools": user.preferences.preferred_tools,
            },
            "learned_patterns": [
                {
                    "type": p.pattern_type,
                    "description": p.description,
                    "confidence": p.confidence,
                }
                for p in user.learned_patterns
            ],
            "member_since": user.created_at.isoformat(),
        }
        
        return ToolResult(
            success=True,
            data=profile,
            message="Retrieved user profile",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting profile: {str(e)}",
        )


async def update_user_preference(
    user_id: str,
    preference_name: str,
    preference_value: Any,
    user_repository: Any,
) -> ToolResult:
    """Update a user preference.
    
    Args:
        user_id: The user's ID
        preference_name: Name of the preference to update
        preference_value: New value for the preference
        user_repository: Repository for user data
        
    Returns:
        ToolResult indicating success
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        user = await user_repository.get(UserId.from_string(user_id))
        if not user:
            return ToolResult(
                success=False,
                data=None,
                message="User not found",
            )
        
        # Validate preference name
        valid_prefs = ["temperature", "auto_plan", "verbose_responses", "default_model"]
        if preference_name not in valid_prefs:
            return ToolResult(
                success=False,
                data=None,
                message=f"Invalid preference. Valid options: {valid_prefs}",
            )
        
        user = user.update_preferences(**{preference_name: preference_value})
        await user_repository.update(user)
        
        return ToolResult(
            success=True,
            data={preference_name: preference_value},
            message=f"Updated {preference_name} to {preference_value}",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error updating preference: {str(e)}",
        )


async def remember_about_user(
    user_id: str,
    pattern_type: str,
    description: str,
    user_repository: Any,
) -> ToolResult:
    """Remember something about the user (learned pattern).
    
    Args:
        user_id: The user's ID
        pattern_type: Type of pattern (e.g., "coding_style", "communication")
        description: Description of what was learned
        user_repository: Repository for user data
        
    Returns:
        ToolResult indicating success
    """
    try:
        from agent_system.domain.value_objects import UserId
        from agent_system.domain.entities import LearnedPattern
        
        user = await user_repository.get(UserId.from_string(user_id))
        if not user:
            return ToolResult(
                success=False,
                data=None,
                message="User not found",
            )
        
        pattern = LearnedPattern(
            pattern_type=pattern_type,
            description=description,
            confidence=0.7,
        )
        
        user = user.add_learned_pattern(pattern)
        await user_repository.update(user)
        
        return ToolResult(
            success=True,
            data={"pattern_type": pattern_type, "description": description},
            message=f"Remembered: {description}",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error remembering: {str(e)}",
        )


# ============ Conversation Analysis Tools ============

async def get_conversation_history(
    user_id: str,
    conversation_repository: Any,
    limit: int = 5,
) -> ToolResult:
    """Get recent conversation summaries for the user.
    
    Args:
        user_id: The user's ID
        conversation_repository: Repository for conversations
        limit: Number of conversations to return
        
    Returns:
        ToolResult with conversation summaries
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        conversations = await conversation_repository.get_by_user(
            UserId.from_string(user_id),
            limit=limit,
        )
        
        summaries = []
        for conv in conversations:
            summaries.append({
                "id": str(conv.id),
                "title": conv.metadata.title or "Untitled",
                "message_count": conv.message_count,
                "last_updated": conv.updated_at.isoformat(),
                "summary": conv.metadata.summary,
                "tags": conv.metadata.tags,
            })
        
        return ToolResult(
            success=True,
            data=summaries,
            message=f"Found {len(summaries)} recent conversations",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting history: {str(e)}",
        )


async def analyze_conversation_patterns(
    user_id: str,
    conversation_repository: Any,
) -> ToolResult:
    """Analyze patterns in user's conversations.
    
    Args:
        user_id: The user's ID
        conversation_repository: Repository for conversations
        
    Returns:
        ToolResult with pattern analysis
    """
    try:
        from agent_system.domain.value_objects import UserId, MessageRole
        
        conversations = await conversation_repository.get_by_user(
            UserId.from_string(user_id),
            limit=20,
        )
        
        if not conversations:
            return ToolResult(
                success=True,
                data={"message": "No conversations to analyze"},
                message="No conversation history found",
            )
        
        # Analyze patterns
        total_messages = 0
        user_messages = 0
        total_tokens = 0
        topics = []
        
        for conv in conversations:
            total_messages += conv.message_count
            total_tokens += conv.metadata.total_tokens_used
            topics.extend(conv.metadata.topic_keywords)
            
            for msg in conv.messages:
                if msg.message.role == MessageRole.USER:
                    user_messages += 1
        
        # Count topic frequency
        topic_counts = {}
        for topic in topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        
        top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        analysis = {
            "total_conversations": len(conversations),
            "total_messages": total_messages,
            "user_messages": user_messages,
            "total_tokens_used": total_tokens,
            "avg_messages_per_conversation": total_messages / len(conversations) if conversations else 0,
            "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        }
        
        return ToolResult(
            success=True,
            data=analysis,
            message="Conversation patterns analyzed",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error analyzing patterns: {str(e)}",
        )


# ============ Fun/Utility Tools ============

async def get_current_datetime(
    user_id: str | None = None,
    user_repository: Any = None,
) -> ToolResult:
    """Get the current date and time in the user's timezone.
    
    Args:
        user_id: The user's ID (optional, for timezone lookup)
        user_repository: Repository for user data (optional)
    
    Returns:
        ToolResult with current datetime in user's timezone
    """
    from datetime import timezone as dt_timezone
    from zoneinfo import ZoneInfo
    
    user_tz_name = "UTC"
    
    # Try to get user's timezone
    if user_id and user_repository:
        try:
            from agent_system.domain.value_objects import UserId
            user = await user_repository.get(UserId.from_string(user_id))
            if user and user.timezone:
                user_tz_name = user.timezone
        except Exception:
            pass  # Fall back to UTC
    
    # Get current time in UTC and convert to user's timezone
    utc_now = datetime.now(dt_timezone.utc)
    try:
        user_tz = ZoneInfo(user_tz_name)
        now = utc_now.astimezone(user_tz)
    except Exception:
        now = utc_now
        user_tz_name = "UTC"
    
    return ToolResult(
        success=True,
        data={
            "datetime": now.isoformat(),
            "date": now.strftime("%B %d, %Y"),
            "time": now.strftime("%I:%M %p"),
            "day_of_week": now.strftime("%A"),
            "timezone": user_tz_name,
            "timezone_abbrev": now.strftime("%Z"),
            "timestamp": now.timestamp(),
        },
        message=f"Current time: {now.strftime('%B %d, %Y at %I:%M %p %Z')} ({user_tz_name})",
    )


async def calculate(expression: str) -> ToolResult:
    """Safely evaluate a mathematical expression.
    
    Args:
        expression: Mathematical expression to evaluate
        
    Returns:
        ToolResult with calculation result
    """
    try:
        # Safe evaluation - only allow math operations
        import ast
        import operator
        
        # Allowed operators
        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
            ast.Mod: operator.mod,
        }
        
        def eval_expr(node):
            if isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.BinOp):
                return ops[type(node.op)](eval_expr(node.left), eval_expr(node.right))
            elif isinstance(node, ast.UnaryOp):
                return ops[type(node.op)](eval_expr(node.operand))
            else:
                raise ValueError(f"Unsupported operation: {type(node)}")
        
        tree = ast.parse(expression, mode='eval')
        result = eval_expr(tree.body)
        
        return ToolResult(
            success=True,
            data={"expression": expression, "result": result},
            message=f"{expression} = {result}",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Calculation error: {str(e)}",
        )


async def generate_random_fact() -> ToolResult:
    """Generate a random interesting fact.
    
    Returns:
        ToolResult with a random fact
    """
    import random
    
    facts = [
        "Honey never spoils. Archaeologists have found 3000-year-old honey in Egyptian tombs that was still edible.",
        "Octopuses have three hearts and blue blood.",
        "A day on Venus is longer than a year on Venus.",
        "Bananas are berries, but strawberries aren't.",
        "The shortest war in history lasted 38-45 minutes (Britain vs Zanzibar, 1896).",
        "A group of flamingos is called a 'flamboyance'.",
        "The inventor of the Pringles can is buried in one.",
        "Cows have best friends and get stressed when separated.",
        "The unicorn is the national animal of Scotland.",
        "A jiffy is an actual unit of time: 1/100th of a second.",
        "The first computer programmer was a woman - Ada Lovelace in the 1840s.",
        "Python was named after Monty Python, not the snake.",
        "The first domain ever registered was symbolics.com in 1985.",
        "More people have cell phones than toilets worldwide.",
        "The average person spends 6 months of their life waiting for red lights.",
    ]
    
    fact = random.choice(facts)
    
    return ToolResult(
        success=True,
        data={"fact": fact},
        message=fact,
    )


async def get_word_definition(word: str) -> ToolResult:
    """Get the definition of a word using a free dictionary API.
    
    Args:
        word: The word to define
        
    Returns:
        ToolResult with word definition
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
                timeout=10.0,
            )
            
            if response.status_code == 404:
                return ToolResult(
                    success=False,
                    data=None,
                    message=f"Word '{word}' not found in dictionary",
                )
            
            if response.status_code != 200:
                return ToolResult(
                    success=False,
                    data=None,
                    message=f"Dictionary lookup failed",
                )
            
            data = response.json()
            if not data:
                return ToolResult(
                    success=False,
                    data=None,
                    message=f"No definition found for '{word}'",
                )
            
            entry = data[0]
            definitions = []
            
            for meaning in entry.get("meanings", [])[:3]:
                part_of_speech = meaning.get("partOfSpeech", "")
                for defn in meaning.get("definitions", [])[:2]:
                    definitions.append({
                        "part_of_speech": part_of_speech,
                        "definition": defn.get("definition", ""),
                        "example": defn.get("example"),
                    })
            
            return ToolResult(
                success=True,
                data={
                    "word": word,
                    "phonetic": entry.get("phonetic", ""),
                    "definitions": definitions,
                },
                message=f"Found {len(definitions)} definitions for '{word}'",
            )
            
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Dictionary error: {str(e)}",
        )


# ============ Knowledge Graph Tools ============

async def summarize_user_knowledge(
    user_id: str,
    knowledge_graph_port: Any,
) -> ToolResult:
    """Summarize the user's knowledge graph - their interests, topics, interactions, and patterns.
    
    This provides a comprehensive view of what the system knows about the user based on
    their conversation history and interactions.
    
    Args:
        user_id: The user's ID
        knowledge_graph_port: The knowledge graph adapter
        
    Returns:
        ToolResult with knowledge summary including topics, interests, tools used, and interaction patterns
    """
    try:
        from agent_system.domain.value_objects import UserId
        from agent_system.domain.entities import KnowledgeNodeType
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        # Get all user's nodes from the knowledge graph
        user_nodes = await knowledge_graph_port.get_user_nodes(
            user_id=UserId.from_string(user_id),
            node_type=None,  # All types
        )
        
        if not user_nodes:
            return ToolResult(
                success=True,
                data={
                    "summary": "No knowledge graph data yet. Start chatting to build your profile!",
                    "topics": [],
                    "interactions": [],
                    "tools_used": [],
                },
                message="No knowledge graph data found for this user",
            )
        
        # Categorize nodes by type
        topics = []
        interactions = []
        tools_used = []
        suggestions = []
        user_info = None
        
        for node in user_nodes:
            node_type = node.node_type.value
            
            if node_type == "user":
                user_info = {
                    "label": node.label,
                    "created_at": node.created_at.isoformat() if node.created_at else None,
                }
            elif node_type == "topic":
                topics.append({
                    "name": node.label,
                    "properties": node.properties,
                })
            elif node_type == "interaction":
                interactions.append({
                    "summary": node.label,
                    "timestamp": node.created_at.isoformat() if node.created_at else None,
                    "properties": node.properties,
                })
            elif node_type == "tool":
                tools_used.append({
                    "name": node.label,
                    "properties": node.properties,
                })
            elif node_type == "suggestion":
                suggestions.append({
                    "title": node.label,
                    "properties": node.properties,
                })
        
        # Build summary
        topic_names = [t["name"] for t in topics]
        tool_names = list(set(t["name"] for t in tools_used))
        
        summary_parts = []
        
        if topic_names:
            # Group similar topics
            unique_topics = list(set(topic_names))[:15]
            summary_parts.append(f"**Topics of Interest ({len(unique_topics)}):** {', '.join(unique_topics)}")
        
        if interactions:
            summary_parts.append(f"**Total Interactions:** {len(interactions)}")
            # Show recent interactions
            recent = sorted(interactions, key=lambda x: x.get("timestamp") or "", reverse=True)[:5]
            if recent:
                recent_summaries = [i["summary"][:50] + "..." if len(i["summary"]) > 50 else i["summary"] for i in recent]
                summary_parts.append(f"**Recent Topics:** {'; '.join(recent_summaries)}")
        
        if tool_names:
            summary_parts.append(f"**Tools Used:** {', '.join(tool_names)}")
        
        if suggestions:
            suggestion_titles = [s["title"] for s in suggestions[:5]]
            summary_parts.append(f"**Suggestions:** {', '.join(suggestion_titles)}")
        
        # Create a narrative summary
        narrative = ""
        if topic_names:
            top_topics = list(set(topic_names))[:5]
            narrative = f"Based on your conversations, you seem interested in: {', '.join(top_topics)}. "
        if interactions:
            narrative += f"You've had {len(interactions)} recorded interactions. "
        if tool_names:
            narrative += f"You've used these tools: {', '.join(tool_names)}. "
        
        return ToolResult(
            success=True,
            data={
                "summary": narrative or "Building your knowledge profile...",
                "formatted_summary": "\n".join(summary_parts) if summary_parts else "No data yet",
                "stats": {
                    "total_nodes": len(user_nodes),
                    "topics_count": len(topics),
                    "interactions_count": len(interactions),
                    "tools_count": len(tools_used),
                },
                "topics": topic_names[:20],
                "recent_interactions": [i["summary"] for i in interactions[:10]],
                "tools_used": tool_names,
                "user_info": user_info,
            },
            message=f"Found {len(user_nodes)} nodes in knowledge graph: {len(topics)} topics, {len(interactions)} interactions, {len(tools_used)} tool uses",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error summarizing knowledge: {str(e)}",
        )


async def recall_about_topic(
    topic: str,
    user_id: str,
    knowledge_graph_port: Any,
    embedding_port: Any = None,
) -> ToolResult:
    """Recall what the system knows about a specific topic or entity using semantic search.
    
    Uses embedding-based semantic search to find contextually related information,
    not just exact keyword matches. This finds mentions even when exact words differ.
    
    Args:
        topic: The topic, person, pet, or entity to look up (e.g., "Bo", "Zane", "cats")
        user_id: The user's ID
        knowledge_graph_port: The knowledge graph adapter (with vector search)
        embedding_port: The embedding adapter for generating query embeddings
        
    Returns:
        ToolResult with everything known about the topic
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        results = {
            "topic": topic,
            "semantic_matches": [],
            "from_knowledge_graph": [],
        }
        
        topic_lower = topic.lower()
        user_id_obj = UserId.from_string(user_id)
        
        # Primary: Semantic search using embeddings
        if embedding_port and knowledge_graph_port:
            try:
                # Generate embedding for the search query
                query_text = f"Information about {topic}"
                query_embedding = await embedding_port.embed(query_text)
                
                # Perform semantic search
                semantic_results = await knowledge_graph_port.semantic_search(
                    user_id=user_id_obj,
                    query_embedding=query_embedding.embedding,
                    limit=15,
                    min_score=0.3,  # Lower threshold to catch more relevant content
                )
                
                # Also search with just the topic name for better matching
                topic_embedding = await embedding_port.embed(topic)
                topic_results = await knowledge_graph_port.semantic_search(
                    user_id=user_id_obj,
                    query_embedding=topic_embedding.embedding,
                    limit=10,
                    min_score=0.35,
                )
                
                # Combine and deduplicate results
                seen_ids = set()
                for result in semantic_results + topic_results:
                    if result["id"] not in seen_ids:
                        seen_ids.add(result["id"])
                        results["semantic_matches"].append({
                            "content": result["content"],
                            "role": result["role"],
                            "score": round(result["score"], 3),
                            "conversation_id": result.get("conversation_id"),
                        })
                
                # Sort by score
                results["semantic_matches"].sort(key=lambda x: x["score"], reverse=True)
                results["semantic_matches"] = results["semantic_matches"][:10]
                
            except Exception as e:
                results["semantic_error"] = str(e)
        
        # Fallback: Use Neo4j keyword-based recall (MessageEmbedding + KnowledgeNode)
        if knowledge_graph_port:
            try:
                keyword_results = await knowledge_graph_port.recall_about_topic(
                    user_id=user_id_obj,
                    topic=topic,
                    limit=5,
                )
                for rec in keyword_results:
                    content = rec.get("content", "")
                    role = rec.get("role", "knowledge")
                    source_type = rec.get("source_type", "knowledge")
                    if content and not any(
                        r.get("content") == content for r in results["semantic_matches"]
                    ):
                        results["from_knowledge_graph"].append({
                            "type": source_type,
                            "label": content[:200],
                            "properties": {"content": content, "role": role},
                        })
                
                # Also search knowledge graph nodes for topic mentions
                user_nodes = await knowledge_graph_port.get_user_nodes(
                    user_id=user_id_obj,
                    node_type=None,
                )
                for node in user_nodes:
                    label_lower = node.label.lower()
                    props_str = str(node.properties).lower()
                    if topic_lower in label_lower or topic_lower in props_str:
                        if not any(
                            r.get("label", "").startswith(node.label[:50])
                            for r in results["from_knowledge_graph"]
                        ):
                            results["from_knowledge_graph"].append({
                                "type": node.node_type.value,
                                "label": node.label,
                                "properties": node.properties,
                            })
            except Exception as e:
                results["knowledge_graph_error"] = str(e)
        
        # Build a summary
        semantic_count = len(results["semantic_matches"])
        kg_count = len(results["from_knowledge_graph"])
        
        if semantic_count == 0 and kg_count == 0:
            return ToolResult(
                success=True,
                data=results,
                message=f"No information found about '{topic}'. This topic hasn't been discussed in our conversations yet.",
            )
        
        # Format the findings
        summary_parts = []
        
        if semantic_count > 0:
            summary_parts.append(f"**Found {semantic_count} Related Conversations:**\n")
            for i, match in enumerate(results["semantic_matches"][:8], 1):
                role_label = "You said" if match["role"] == "user" else "I said"
                content_preview = match["content"][:300]
                if len(match["content"]) > 300:
                    content_preview += "..."
                summary_parts.append(f"{i}. ({match['score']:.0%} match) {role_label}: \"{content_preview}\"\n")
        
        if kg_count > 0:
            summary_parts.append(f"\n**Knowledge Graph ({kg_count} entries):**")
            for item in results["from_knowledge_graph"][:5]:
                summary_parts.append(f"- [{item['type']}] {item['label']}")
        
        formatted = "\n".join(summary_parts)
        
        return ToolResult(
            success=True,
            data=results,
            message=f"Here's what I know about '{topic}':\n\n{formatted}",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error recalling about '{topic}': {str(e)}",
        )


async def recall_group_topic(
    topic: str,
    group_id: str,
    knowledge_graph_port: Any,
    embedding_port: Any = None,
) -> ToolResult:
    """Recall what the group has discussed about a specific topic using semantic search.
    
    Searches across all group conversations to find relevant discussions shared
    among group members.
    
    Args:
        topic: The topic to look up
        group_id: The group identifier
        knowledge_graph_port: The knowledge graph adapter (with group search)
        embedding_port: The embedding adapter for generating query embeddings
        
    Returns:
        ToolResult with group knowledge about the topic
    """
    try:
        results = {
            "topic": topic,
            "group_id": group_id,
            "semantic_matches": [],
            "from_knowledge_graph": [],
        }
        
        # Primary: Semantic search using embeddings
        if embedding_port and knowledge_graph_port:
            try:
                # Generate embedding for the search query
                query_text = f"Discussion about {topic}"
                query_embedding = await embedding_port.embed(query_text)
                
                # Perform semantic search within the group
                semantic_results = await knowledge_graph_port.group_semantic_search(
                    group_id=group_id,
                    query_embedding=query_embedding.embedding,
                    limit=15,
                    min_score=0.3,
                )
                
                # Also search with just the topic name
                topic_embedding = await embedding_port.embed(topic)
                topic_results = await knowledge_graph_port.group_semantic_search(
                    group_id=group_id,
                    query_embedding=topic_embedding.embedding,
                    limit=10,
                    min_score=0.35,
                )
                
                # Combine and deduplicate results
                seen_ids = set()
                for result in semantic_results + topic_results:
                    if result["id"] not in seen_ids:
                        seen_ids.add(result["id"])
                        results["semantic_matches"].append({
                            "content": result["content"],
                            "role": result["role"],
                            "user_email": result.get("user_email", "Unknown"),
                            "score": round(result["score"], 3),
                            "conversation_id": result.get("conversation_id"),
                        })
                
                # Sort by score
                results["semantic_matches"].sort(key=lambda x: x["score"], reverse=True)
                results["semantic_matches"] = results["semantic_matches"][:10]
                
            except Exception as e:
                results["semantic_error"] = str(e)
        
        # Also get group knowledge graph nodes
        if knowledge_graph_port:
            try:
                group_nodes = await knowledge_graph_port.get_group_knowledge(
                    group_id=group_id,
                    limit=20,
                )
                
                topic_lower = topic.lower()
                for node in group_nodes:
                    label_lower = node.label.lower()
                    props_str = str(node.properties).lower()
                    
                    if topic_lower in label_lower or topic_lower in props_str:
                        results["from_knowledge_graph"].append({
                            "type": node.node_type.value,
                            "label": node.label,
                            "properties": node.properties,
                        })
            except Exception as e:
                results["knowledge_graph_error"] = str(e)
        
        # Build summary
        semantic_count = len(results["semantic_matches"])
        kg_count = len(results["from_knowledge_graph"])
        
        if semantic_count == 0 and kg_count == 0:
            return ToolResult(
                success=True,
                data=results,
                message=f"No group discussions found about '{topic}'. This topic hasn't been discussed in this group yet.",
            )
        
        # Format findings
        summary_parts = []
        
        if semantic_count > 0:
            summary_parts.append(f"**Found {semantic_count} Related Group Discussions:**\n")
            for i, match in enumerate(results["semantic_matches"][:8], 1):
                user_label = match["user_email"]
                if match["role"] == "assistant":
                    user_label = "Assistant"
                content_preview = match["content"][:250]
                if len(match["content"]) > 250:
                    content_preview += "..."
                summary_parts.append(f"{i}. ({match['score']:.0%} match) **{user_label}**: \"{content_preview}\"\n")
        
        if kg_count > 0:
            summary_parts.append(f"\n**Group Knowledge ({kg_count} entries):**")
            for item in results["from_knowledge_graph"][:5]:
                summary_parts.append(f"- [{item['type']}] {item['label']}")
        
        formatted = "\n".join(summary_parts)
        
        return ToolResult(
            success=True,
            data=results,
            message=f"Here's what the group has discussed about '{topic}':\n\n{formatted}",
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error searching group history for '{topic}': {str(e)}",
        )


# ============ Internal Docs Search Tool ============

async def search_internal_docs_tool(query: str, max_sections: int = 5) -> ToolResult:
    """Search internal documentation about how the app works.

    Use when users ask about: knowledge graph, semantic search, conversational
    history, memory, how the system remembers information, or general "how does
    X work" questions about the app.

    Args:
        query: Search terms (e.g. "knowledge graph", "semantic search", "memory")
        max_sections: Maximum sections to return (default 5)

    Returns:
        ToolResult with relevant doc sections
    """
    try:
        from agent_system.docs import search_internal_docs

        results = search_internal_docs(query, max_sections=max_sections)
        if not results:
            return ToolResult(
                success=True,
                data=[],
                message="No internal documentation found matching that query.",
            )
        formatted = [
            {"title": r["title"], "content": r["content"], "relevance": r["relevance"]}
            for r in results
        ]
        return ToolResult(
            success=True,
            data=formatted,
            message=f"Found {len(results)} relevant sections. Use this content to answer the user accurately.",
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error searching internal docs: {str(e)}",
        )


# ============ Event Lookup Tool ============

async def get_upcoming_events(
    user_id: str,
    timeframe: str = "week",
    group_id: str | None = None,
    search_query: str | None = None,
    temporal_filter: str = "future",
    specific_date: str | None = None,
    **kwargs,
) -> ToolResult:
    """Find events with flexible filtering options.
    
    Args:
        user_id: The user's ID
        timeframe: Time period to search - "today", "tomorrow", "week", "month", or "all"
        group_id: Optional group ID to filter events (None = all user's groups)
        search_query: Optional keyword to filter events by title/description (e.g., "haircut", "meeting")
        temporal_filter: "past", "current", "future", or "all" (default: "future")
        specific_date: Optional specific date string (e.g., "2026-01-30", "January 30")
        **kwargs: Must include 'session' for database access
        
    Returns:
        ToolResult with matching events
    """
    try:
        session = kwargs.get("session")
        if not session:
            return ToolResult(
                success=False,
                data=None,
                message="Database session not available",
            )
        
        from datetime import timedelta, timezone as dt_timezone
        from zoneinfo import ZoneInfo
        from sqlalchemy import select, and_, or_
        from agent_system.adapters.outbound.persistence.models import ExtractedEventModel, GroupMembershipModel, UserModel
        
        # Get user's timezone
        user_tz_name = "UTC"
        try:
            user_query = select(UserModel.timezone).where(UserModel.id == user_id)
            result = await session.execute(user_query)
            row = result.fetchone()
            if row and row[0]:
                user_tz_name = row[0]
        except Exception:
            pass
        
        # Get current time in user's timezone
        utc_now = datetime.now(dt_timezone.utc)
        try:
            user_tz = ZoneInfo(user_tz_name)
            now = utc_now.astimezone(user_tz).replace(tzinfo=None)  # Naive in user's tz
        except Exception:
            user_tz = ZoneInfo("UTC")
            now = utc_now.replace(tzinfo=None)
        
        # Parse specific_date if provided
        parsed_specific_date = None
        if specific_date:
            try:
                # Try ISO format first
                parsed_specific_date = datetime.strptime(specific_date, "%Y-%m-%d")
            except ValueError:
                try:
                    # Try "Month Day" format (e.g., "January 30")
                    parsed_specific_date = datetime.strptime(f"{specific_date} {now.year}", "%B %d %Y")
                except ValueError:
                    try:
                        # Try "Month Day, Year" format
                        parsed_specific_date = datetime.strptime(specific_date, "%B %d, %Y")
                    except ValueError:
                        pass  # Failed to parse, will use timeframe instead
        
        # Determine date range based on temporal_filter and timeframe
        if parsed_specific_date:
            # Specific date takes priority
            start_date = parsed_specific_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = parsed_specific_date.replace(hour=23, minute=59, second=59)
            timeframe_desc = f"on {parsed_specific_date.strftime('%B %d, %Y')}"
        elif temporal_filter == "past":
            # Past events (last 30 days up to now)
            start_date = now - timedelta(days=30)
            end_date = now
            timeframe_desc = "in the past 30 days"
        elif temporal_filter == "current":
            # Events happening right now (within the current hour)
            start_date = now.replace(minute=0, second=0, microsecond=0)
            end_date = now.replace(minute=59, second=59)
            timeframe_desc = "happening now"
        elif timeframe == "today":
            # Show all events for today, including ones that have passed
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=23, minute=59, second=59)
            timeframe_desc = "today"
        elif timeframe == "tomorrow":
            tomorrow = now + timedelta(days=1)
            start_date = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = tomorrow.replace(hour=23, minute=59, second=59)
            timeframe_desc = "tomorrow"
        elif timeframe == "week":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now + timedelta(days=7)
            timeframe_desc = "the next 7 days"
        elif timeframe == "month":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now + timedelta(days=30)
            timeframe_desc = "the next 30 days"
        else:  # "all" or default
            start_date = now - timedelta(days=30)  # Include recent past events too
            end_date = now + timedelta(days=365)
            timeframe_desc = "upcoming"
        
        # Get user's group memberships
        membership_query = select(GroupMembershipModel.group_id).where(
            GroupMembershipModel.user_id == user_id
        )
        membership_result = await session.execute(membership_query)
        user_group_ids = [str(row[0]) for row in membership_result.fetchall()]
        
        if not user_group_ids:
            return ToolResult(
                success=True,
                data=[],
                message=f"You're not a member of any groups yet, so no events to show.",
            )
        
        # Filter by specific group if provided
        if group_id and group_id in user_group_ids:
            search_group_ids = [group_id]
        else:
            search_group_ids = user_group_ids
        
        # Build query conditions
        conditions = [ExtractedEventModel.group_id.in_(search_group_ids)]
        
        # Convert date range to UTC for database comparison
        # start_date and end_date are naive in user's timezone, DB stores UTC
        # ZoneInfo works with .replace(tzinfo=) for naive datetimes
        start_date_utc = start_date.replace(tzinfo=user_tz).astimezone(dt_timezone.utc).replace(tzinfo=None)
        end_date_utc = end_date.replace(tzinfo=user_tz).astimezone(dt_timezone.utc).replace(tzinfo=None)
        
        # Date range condition - ONLY include events with a specific datetime
        # Events without datetime are not useful for "what do I have planned" queries
        date_condition = and_(
            ExtractedEventModel.event_datetime.isnot(None),
            ExtractedEventModel.event_datetime >= start_date_utc,
            ExtractedEventModel.event_datetime <= end_date_utc,
        )
        conditions.append(date_condition)
        
        # Search query filter (case-insensitive search in title and description)
        if search_query:
            search_pattern = f"%{search_query.lower()}%"
            search_condition = or_(
                ExtractedEventModel.title.ilike(search_pattern),
                ExtractedEventModel.description.ilike(search_pattern),
                ExtractedEventModel.location.ilike(search_pattern),
            )
            conditions.append(search_condition)
            timeframe_desc = f"matching '{search_query}'"
        
        # Query events
        event_query = select(ExtractedEventModel).where(
            and_(*conditions)
        ).order_by(ExtractedEventModel.event_datetime.asc().nulls_last())
        
        result = await session.execute(event_query)
        events = result.scalars().all()
        
        # Build response message
        if search_query:
            no_results_msg = f"No events found matching '{search_query}'. Try a different search term."
        else:
            no_results_msg = f"No events found for {timeframe_desc}. Your schedule is clear!"
        
        if not events:
            return ToolResult(
                success=True,
                data=[],
                message=no_results_msg,
            )
        
        # Format events for display (convert UTC to user's timezone)
        event_list = []
        for event in events:
            event_info = {
                "title": event.title,
                "type": event.event_type,
                "description": event.description,
                "location": event.location,
                "confirmed": event.is_confirmed,
            }
            if event.event_datetime:
                # Convert from UTC to user's timezone
                try:
                    utc_dt = event.event_datetime.replace(tzinfo=dt_timezone.utc)
                    local_dt = utc_dt.astimezone(user_tz)
                    event_info["datetime"] = local_dt.strftime("%A, %B %d at %I:%M %p %Z")
                except Exception:
                    event_info["datetime"] = event.event_datetime.strftime("%A, %B %d at %I:%M %p")
            else:
                event_info["datetime"] = "Time not specified"
            event_list.append(event_info)
        
        # Build summary as markdown table
        summary_lines = [f"📅 **Found {len(events)} event(s) for {timeframe_desc}:**\n"]
        summary_lines.append("| Status | Event | When | Location | Notes |")
        summary_lines.append("|:------:|-------|------|----------|-------|")
        
        for ev in event_list:
            status = "✅" if ev["confirmed"] else "❓"
            title = ev["title"]
            when = ev["datetime"]
            location = ev["location"] or "—"
            notes = ev["description"][:50] + "..." if ev["description"] and len(ev["description"]) > 50 else (ev["description"] or "—")
            summary_lines.append(f"| {status} | {title} | {when} | {location} | {notes} |")
        
        return ToolResult(
            success=True,
            data=event_list,
            message="\n".join(summary_lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error finding events: {str(e)}",
        )


# ============ Houston Events Tool ============

async def get_houston_events(
    query: str | None = None,
    category: str | None = None,
    limit: int = 30,
    **kwargs,
) -> ToolResult:
    """Get Houston area events from the htown_mania event discovery system.
    
    This searches events discovered by an AI-powered event aggregator that
    monitors Houston event sources daily (concerts, cycling, sports, arts, etc.).
    
    Args:
        query: Optional search text (searches title, description, location)
        category: Optional category filter (music, cycling, sports, arts, etc.)
        limit: Maximum events to return (default 15)
        
    Returns:
        ToolResult with list of Houston events
    """
    try:
        from agent_system.adapters.outbound.houston_events import (
            HoustonEventsAdapter,
            format_houston_events_for_display,
        )
        
        adapter = HoustonEventsAdapter()
        try:
            if query or category:
                events = await adapter.search_events(
                    query=query,
                    category=category,
                    limit=limit,
                )
            else:
                events = await adapter.get_latest_events(limit=limit)
            
            if not events:
                return ToolResult(
                    success=True,
                    data=[],
                    message="No Houston events found matching your criteria.",
                )
            
            # Format for display
            formatted = format_houston_events_for_display(events)
            
            # Also return structured data
            events_data = [
                {
                    "title": e.title,
                    "description": e.description,
                    "location": e.location,
                    "start_time": e.start_time.isoformat() if e.start_time else None,
                    "categories": e.categories,
                    "url": e.url,
                }
                for e in events
            ]
            
            return ToolResult(
                success=True,
                data=events_data,
                message=formatted,
            )
        finally:
            await adapter.close()
            
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error fetching Houston events: {str(e)}",
        )


# ============ Social Graph Tools ============

async def get_person_info(
    name: str,
    user_id: str,
    knowledge_graph_port: Any,
) -> ToolResult:
    """Get information about a person in the user's social graph.
    
    Searches by name or alias to find people the user has mentioned.
    
    Args:
        name: The person's name or alias to look up
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        
    Returns:
        ToolResult with person information
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        
        # Try exact name match first
        person = await knowledge_graph_port.get_person(user_id_obj, name)
        
        # If not found, try alias match
        if not person:
            person = await knowledge_graph_port.find_person_by_alias(user_id_obj, name)
        
        if not person:
            return ToolResult(
                success=True,
                data=None,
                message=f"I don't have any information about '{name}' yet. Tell me about them!",
            )
        
        # Get related entities
        relationships = await knowledge_graph_port.get_entity_relationships(
            user_id_obj, "person", person.get("name", name), max_depth=2
        )
        
        # Format the response
        info_parts = [f"**{person.get('name', name)}**"]
        
        if person.get("relationship_type"):
            info_parts.append(f"- Relationship: {person['relationship_type']}")
        if person.get("context_notes"):
            info_parts.append(f"- Notes: {person['context_notes']}")
        if person.get("email"):
            info_parts.append(f"- Email: {person['email']}")
        if person.get("phone"):
            info_parts.append(f"- Phone: {person['phone']}")
        if person.get("aliases"):
            info_parts.append(f"- Also known as: {', '.join(person['aliases'])}")
        
        info_parts.append(f"- Mentioned {person.get('mention_count', 1)} time(s)")
        
        if relationships:
            info_parts.append("\n**Related:**")
            for rel in relationships[:5]:
                info_parts.append(f"- {' → '.join(rel['relationship_path'])} → {rel['related_name']}")
        
        return ToolResult(
            success=True,
            data=person,
            message="\n".join(info_parts),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting person info: {str(e)}",
        )


async def get_pet_info(
    name: str,
    user_id: str,
    knowledge_graph_port: Any,
) -> ToolResult:
    """Get information about a pet in the user's household.
    
    Args:
        name: The pet's name
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        
    Returns:
        ToolResult with pet information
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        pet = await knowledge_graph_port.get_pet(user_id_obj, name)
        
        if not pet:
            return ToolResult(
                success=True,
                data=None,
                message=f"I don't have any information about a pet named '{name}' yet. Tell me about them!",
            )
        
        # Format the response
        info_parts = [f"**{pet.get('name', name)}**"]
        
        if pet.get("species"):
            info_parts.append(f"- Species: {pet['species']}")
        if pet.get("breed"):
            info_parts.append(f"- Breed: {pet['breed']}")
        if pet.get("personality"):
            info_parts.append(f"- Personality: {', '.join(pet['personality'])}")
        if pet.get("food_preferences"):
            info_parts.append(f"- Food preferences: {', '.join(pet['food_preferences'])}")
        if pet.get("health_notes"):
            info_parts.append(f"- Health notes: {pet['health_notes']}")
        if pet.get("aliases"):
            info_parts.append(f"- Nicknames: {', '.join(pet['aliases'])}")
        
        info_parts.append(f"- Mentioned {pet.get('mention_count', 1)} time(s)")
        
        return ToolResult(
            success=True,
            data=pet,
            message="\n".join(info_parts),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting pet info: {str(e)}",
        )


async def get_location_info(
    name: str,
    user_id: str,
    knowledge_graph_port: Any,
) -> ToolResult:
    """Get information about a location the user frequents.
    
    Args:
        name: The location name
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        
    Returns:
        ToolResult with location information
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        location = await knowledge_graph_port.get_location(user_id_obj, name)
        
        if not location:
            return ToolResult(
                success=True,
                data=None,
                message=f"I don't have any information about '{name}' yet. Tell me about this place!",
            )
        
        # Format the response
        info_parts = [f"**{location.get('name', name)}**"]
        
        if location.get("location_type"):
            info_parts.append(f"- Type: {location['location_type']}")
        if location.get("address"):
            info_parts.append(f"- Address: {location['address']}")
        if location.get("city"):
            info_parts.append(f"- City: {location['city']}")
        if location.get("neighborhood"):
            info_parts.append(f"- Neighborhood: {location['neighborhood']}")
        if location.get("associated_activities"):
            info_parts.append(f"- Activities: {', '.join(location['associated_activities'])}")
        if location.get("notes"):
            info_parts.append(f"- Notes: {location['notes']}")
        if location.get("aliases"):
            info_parts.append(f"- Also called: {', '.join(location['aliases'])}")
        
        info_parts.append(f"- Mentioned {location.get('mention_count', 1)} time(s)")
        
        return ToolResult(
            success=True,
            data=location,
            message="\n".join(info_parts),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting location info: {str(e)}",
        )


async def list_known_people(
    user_id: str,
    knowledge_graph_port: Any,
    relationship_type: str | None = None,
) -> ToolResult:
    """List all people in the user's social graph.
    
    Args:
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        relationship_type: Optional filter by relationship (spouse, friend, colleague, etc.)
        
    Returns:
        ToolResult with list of people
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        people = await knowledge_graph_port.list_known_people(
            user_id_obj,
            relationship_type=relationship_type,
            limit=50,
        )
        
        if not people:
            filter_msg = f" with relationship '{relationship_type}'" if relationship_type else ""
            return ToolResult(
                success=True,
                data=[],
                message=f"I don't know any people{filter_msg} yet. Tell me about the people in your life!",
            )
        
        # Format the response
        lines = [f"**People I Know About ({len(people)}):**\n"]
        
        for person in people:
            rel = f" ({person.get('relationship_type')})" if person.get("relationship_type") else ""
            mentions = f" - {person.get('mention_count', 1)} mentions"
            lines.append(f"- **{person.get('name')}**{rel}{mentions}")
        
        return ToolResult(
            success=True,
            data=people,
            message="\n".join(lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error listing people: {str(e)}",
        )


async def list_pets(
    user_id: str,
    knowledge_graph_port: Any,
    species: str | None = None,
) -> ToolResult:
    """List all pets in the user's household.
    
    Args:
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        species: Optional filter by species (dog, cat, etc.)
        
    Returns:
        ToolResult with list of pets
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        pets = await knowledge_graph_port.list_pets(user_id_obj, species=species)
        
        if not pets:
            filter_msg = f" ({species})" if species else ""
            return ToolResult(
                success=True,
                data=[],
                message=f"I don't know about any pets{filter_msg} yet. Tell me about your furry friends!",
            )
        
        # Format the response
        lines = [f"**Your Pets ({len(pets)}):**\n"]
        
        for pet in pets:
            species_str = f" the {pet.get('species')}" if pet.get("species") else ""
            breed_str = f" ({pet.get('breed')})" if pet.get("breed") else ""
            lines.append(f"- **{pet.get('name')}**{species_str}{breed_str}")
        
        return ToolResult(
            success=True,
            data=pets,
            message="\n".join(lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error listing pets: {str(e)}",
        )


async def list_locations(
    user_id: str,
    knowledge_graph_port: Any,
    location_type: str | None = None,
    city: str | None = None,
) -> ToolResult:
    """List all locations the user frequents.
    
    Args:
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        location_type: Optional filter by type (restaurant, gym, etc.)
        city: Optional filter by city
        
    Returns:
        ToolResult with list of locations
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        locations = await knowledge_graph_port.list_locations(
            user_id_obj,
            location_type=location_type,
            city=city,
        )
        
        if not locations:
            filter_msg = ""
            if location_type:
                filter_msg = f" of type '{location_type}'"
            if city:
                filter_msg += f" in {city}"
            return ToolResult(
                success=True,
                data=[],
                message=f"I don't know about any locations{filter_msg} yet. Tell me about your favorite places!",
            )
        
        # Format the response
        lines = [f"**Places You Frequent ({len(locations)}):**\n"]
        
        for loc in locations:
            type_str = f" ({loc.get('location_type')})" if loc.get("location_type") else ""
            city_str = f" in {loc.get('city')}" if loc.get("city") else ""
            lines.append(f"- **{loc.get('name')}**{type_str}{city_str}")
        
        return ToolResult(
            success=True,
            data=locations,
            message="\n".join(lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error listing locations: {str(e)}",
        )


async def get_user_preferences(
    user_id: str,
    knowledge_graph_port: Any,
    category: str | None = None,
) -> ToolResult:
    """Get aggregated user preferences from conversations.
    
    Args:
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        category: Optional filter by category (food, activities, schedule, etc.)
        
    Returns:
        ToolResult with user preferences
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        preferences = await knowledge_graph_port.get_user_preferences(
            user_id_obj,
            category=category,
            min_confidence=0.3,
        )
        
        if not preferences:
            filter_msg = f" for '{category}'" if category else ""
            return ToolResult(
                success=True,
                data=[],
                message=f"I haven't learned any preferences{filter_msg} yet. As we chat, I'll remember what you like!",
            )
        
        # Group by category
        by_category: dict[str, list] = {}
        for pref in preferences:
            cat = pref.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(pref)
        
        # Format the response
        lines = [f"**Your Preferences ({len(preferences)}):**\n"]
        
        for cat, prefs in by_category.items():
            lines.append(f"\n**{cat.title()}:**")
            for pref in prefs:
                sentiment = pref.get("sentiment", 0)
                if sentiment > 0.3:
                    emoji = "👍"
                elif sentiment < -0.3:
                    emoji = "👎"
                else:
                    emoji = "➖"
                confidence = pref.get("confidence", 0.5)
                conf_str = f" ({confidence:.0%} confident)" if confidence < 0.8 else ""
                lines.append(f"- {emoji} {pref.get('value')}{conf_str}")
        
        return ToolResult(
            success=True,
            data=preferences,
            message="\n".join(lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting preferences: {str(e)}",
        )


async def get_group_consensus(
    topic: str,
    group_id: str,
    knowledge_graph_port: Any,
) -> ToolResult:
    """Get group consensus on a topic.
    
    Analyzes what group members have discussed about a topic.
    
    Args:
        topic: The topic to get consensus on
        group_id: The group's ID
        knowledge_graph_port: The Neo4j adapter
        
    Returns:
        ToolResult with group consensus information
    """
    try:
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        consensus = await knowledge_graph_port.get_group_consensus(group_id, topic)
        
        if consensus.get("mention_count", 0) == 0:
            return ToolResult(
                success=True,
                data=consensus,
                message=f"No group discussions found about '{topic}' yet.",
            )
        
        # Format the response
        lines = [f"**Group Consensus on '{topic}':**\n"]
        
        lines.append(f"- **Mentions:** {consensus.get('mention_count', 0)}")
        
        users = consensus.get("users_involved", [])
        if users:
            lines.append(f"- **Contributors:** {', '.join(users)}")
        
        mentions = consensus.get("mentions", [])
        if mentions:
            lines.append("\n**Recent Discussions:**")
            for i, mention in enumerate(mentions[:5], 1):
                user = mention.get("user", "Unknown")
                content = mention.get("content", "")[:150]
                if len(mention.get("content", "")) > 150:
                    content += "..."
                lines.append(f"{i}. **{user}**: {content}")
        
        return ToolResult(
            success=True,
            data=consensus,
            message="\n".join(lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting group consensus: {str(e)}",
        )


async def get_thread_history(
    thread_name: str,
    user_id: str,
    knowledge_graph_port: Any,
) -> ToolResult:
    """Get the full history of a cross-conversation thread/project.
    
    Threads track ongoing topics that span multiple conversations.
    
    Args:
        thread_name: Name of the thread/project
        user_id: The user's ID
        knowledge_graph_port: The Neo4j adapter
        
    Returns:
        ToolResult with thread history
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        user_id_obj = UserId.from_string(user_id)
        thread = await knowledge_graph_port.get_thread_history(user_id_obj, thread_name)
        
        if not thread:
            return ToolResult(
                success=True,
                data=None,
                message=f"No thread found named '{thread_name}'. Create one by telling me about an ongoing project!",
            )
        
        # Format the response
        info_parts = [f"**Thread: {thread.get('name', thread_name)}**"]
        
        if thread.get("description"):
            info_parts.append(f"\n{thread['description']}")
        
        info_parts.append(f"\n**Status:** {thread.get('status', 'active')}")
        
        conv_ids = thread.get("conversation_ids", [])
        if conv_ids:
            info_parts.append(f"**Conversations:** {len(conv_ids)} linked")
        
        topics = thread.get("related_topics", [])
        if topics:
            info_parts.append(f"**Topics:** {', '.join(topics)}")
        
        if thread.get("created_at"):
            info_parts.append(f"\n*Started: {thread['created_at']}*")
        if thread.get("last_updated"):
            info_parts.append(f"*Last updated: {thread['last_updated']}*")
        
        return ToolResult(
            success=True,
            data=thread,
            message="\n".join(info_parts),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error getting thread history: {str(e)}",
        )


async def recall_from_period(
    user_id: str,
    start_date: str,
    end_date: str,
    knowledge_graph_port: Any,
    topic: str | None = None,
) -> ToolResult:
    """Recall what was discussed during a specific time period.
    
    Args:
        user_id: The user's ID
        start_date: Start date (ISO format or "YYYY-MM-DD")
        end_date: End date (ISO format or "YYYY-MM-DD")
        knowledge_graph_port: The Neo4j adapter
        topic: Optional topic filter
        
    Returns:
        ToolResult with messages from the period
    """
    try:
        from agent_system.domain.value_objects import UserId
        
        if not knowledge_graph_port:
            return ToolResult(
                success=False,
                data=None,
                message="Knowledge graph not available",
            )
        
        # Parse dates
        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        
        try:
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            end = datetime.strptime(end_date, "%Y-%m-%d")
            end = end.replace(hour=23, minute=59, second=59)
        
        user_id_obj = UserId.from_string(user_id)
        messages = await knowledge_graph_port.recall_from_period(
            user_id_obj,
            start_date=start,
            end_date=end,
            topic=topic,
            limit=20,
        )
        
        if not messages:
            topic_msg = f" about '{topic}'" if topic else ""
            return ToolResult(
                success=True,
                data=[],
                message=f"No conversations found{topic_msg} between {start_date} and {end_date}.",
            )
        
        # Format the response
        lines = [f"**Conversations from {start_date} to {end_date}:**\n"]
        
        for msg in messages:
            role = "You" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:200]
            if len(msg.get("content", "")) > 200:
                content += "..."
            lines.append(f"- **{role}**: {content}")
        
        return ToolResult(
            success=True,
            data=messages,
            message="\n".join(lines),
        )
        
    except Exception as e:
        return ToolResult(
            success=False,
            data=None,
            message=f"Error recalling from period: {str(e)}",
        )


# ============ Tool Registry ============

AVAILABLE_TOOLS = {
    "web_search": {
        "function": web_search,
        "description": "Search the web for information",
        "parameters": {"query": "string", "num_results": "int (optional, default 5)"},
    },
    "search_internal_docs": {
        "function": search_internal_docs_tool,
        "description": "Search internal docs about how the app works (knowledge graph, semantic search, memory, conversational history). Use when users ask 'how does X work', 'how does the knowledge graph work', 'how does semantic search work', etc.",
        "parameters": {"query": "string (search terms, e.g. 'knowledge graph', 'semantic search', 'memory')"},
    },
    "get_user_profile": {
        "function": get_user_profile,
        "description": "Get the current user's profile and preferences",
        "parameters": {"user_id": "string"},
        "requires_repos": True,
    },
    "update_user_preference": {
        "function": update_user_preference,
        "description": "Update a user preference (temperature, auto_plan, verbose_responses, default_model)",
        "parameters": {"user_id": "string", "preference_name": "string", "preference_value": "any"},
        "requires_repos": True,
    },
    "remember_about_user": {
        "function": remember_about_user,
        "description": "Remember something learned about the user",
        "parameters": {"user_id": "string", "pattern_type": "string", "description": "string"},
        "requires_repos": True,
    },
    "get_conversation_history": {
        "function": get_conversation_history,
        "description": "Get recent conversation summaries",
        "parameters": {"user_id": "string", "limit": "int (optional, default 5)"},
        "requires_repos": True,
    },
    "analyze_conversation_patterns": {
        "function": analyze_conversation_patterns,
        "description": "Analyze patterns in user's conversation history",
        "parameters": {"user_id": "string"},
        "requires_repos": True,
    },
    "get_current_datetime": {
        "function": get_current_datetime,
        "description": "Get the current date and time in the user's timezone",
        "parameters": {},
        "requires_repos": True,
    },
    "calculate": {
        "function": calculate,
        "description": "Evaluate a mathematical expression",
        "parameters": {"expression": "string (e.g., '2 + 2 * 3')"},
    },
    "random_fact": {
        "function": generate_random_fact,
        "description": "Get a random interesting fact",
        "parameters": {},
    },
    "define_word": {
        "function": get_word_definition,
        "description": "Look up a word's definition",
        "parameters": {"word": "string"},
    },
    "summarize_user_knowledge": {
        "function": summarize_user_knowledge,
        "description": "Summarize the user's knowledge graph - their interests, topics discussed, tools used, and interaction patterns from their conversation history",
        "parameters": {"user_id": "string"},
        "requires_knowledge_graph": True,
    },
    "recall_about_topic": {
        "function": recall_about_topic,
        "description": "Recall what is known about a specific topic, person, pet, or entity using semantic search across past conversations",
        "parameters": {"topic": "string (the entity to look up, e.g., 'Bo', 'Zane', 'cats')"},
        "requires_knowledge_graph": True,
        "requires_embedding": True,
    },
    "recall_group_topic": {
        "function": recall_group_topic,
        "description": "Recall what the group has discussed about a specific topic using semantic search across group conversations",
        "parameters": {"topic": "string (the topic to look up)", "group_id": "string (injected)"},
        "requires_knowledge_graph": True,
        "requires_embedding": True,
        "requires_group_context": True,
    },
    "get_upcoming_events": {
        "function": get_upcoming_events,
        "description": "Find events with flexible filtering: by timeframe, keyword search, temporal filter (past/future), or specific date",
        "parameters": {
            "timeframe": "string (today, tomorrow, week, month, or all)",
            "search_query": "string (optional keyword to filter by, e.g., 'haircut', 'meeting')",
            "temporal_filter": "string (past, current, future, or all - default: future)",
            "specific_date": "string (optional specific date, e.g., '2026-01-30', 'January 30')",
        },
        "requires_session": True,
    },
    "get_houston_events": {
        "function": get_houston_events,
        "description": "Search Houston area events (concerts, cycling, sports, arts, festivals, etc.) from the htown_mania event discovery system",
        "parameters": {
            "query": "string (optional search text for title/description/location)",
            "category": "string (optional: music, cycling, sports, arts, food, etc.)",
            "limit": "int (optional, default 30)",
        },
    },
    # Social Graph Tools
    "get_person_info": {
        "function": get_person_info,
        "description": "Get information about a person in your social graph (friends, family, colleagues)",
        "parameters": {"name": "string (person's name or nickname)"},
        "requires_knowledge_graph": True,
    },
    "get_pet_info": {
        "function": get_pet_info,
        "description": "Get information about a pet in your household",
        "parameters": {"name": "string (pet's name)"},
        "requires_knowledge_graph": True,
    },
    "get_location_info": {
        "function": get_location_info,
        "description": "Get information about a location you frequent",
        "parameters": {"name": "string (location name)"},
        "requires_knowledge_graph": True,
    },
    "list_known_people": {
        "function": list_known_people,
        "description": "List all people in your social graph",
        "parameters": {"relationship_type": "string (optional: spouse, friend, colleague, family, etc.)"},
        "requires_knowledge_graph": True,
    },
    "list_pets": {
        "function": list_pets,
        "description": "List all pets in your household",
        "parameters": {"species": "string (optional: dog, cat, etc.)"},
        "requires_knowledge_graph": True,
    },
    "list_locations": {
        "function": list_locations,
        "description": "List all locations you frequent",
        "parameters": {
            "location_type": "string (optional: restaurant, gym, office, etc.)",
            "city": "string (optional city filter)",
        },
        "requires_knowledge_graph": True,
    },
    "get_user_preferences": {
        "function": get_user_preferences,
        "description": "Get your preferences learned from conversations (food, activities, schedule, etc.)",
        "parameters": {"category": "string (optional: food, activities, schedule, etc.)"},
        "requires_knowledge_graph": True,
    },
    "recall_from_period": {
        "function": recall_from_period,
        "description": "Recall what was discussed during a specific time period",
        "parameters": {
            "start_date": "string (YYYY-MM-DD format)",
            "end_date": "string (YYYY-MM-DD format)",
            "topic": "string (optional topic filter)",
        },
        "requires_knowledge_graph": True,
    },
    "get_thread_history": {
        "function": get_thread_history,
        "description": "Get the full history of a cross-conversation thread/project",
        "parameters": {"thread_name": "string (name of the thread/project)"},
        "requires_knowledge_graph": True,
    },
    "get_group_consensus": {
        "function": get_group_consensus,
        "description": "Get group consensus on a topic - what group members have discussed about it",
        "parameters": {"topic": "string (topic to get consensus on)"},
        "requires_knowledge_graph": True,
        "requires_group_context": True,
    },
}


def get_tools_description() -> str:
    """Get a formatted description of all available tools."""
    lines = ["Available tools:"]
    for name, info in AVAILABLE_TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["parameters"].items())
        lines.append(f"- {name}({params}): {info['description']}")
    return "\n".join(lines)
