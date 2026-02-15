"""FSM workflow nodes using pydantic-graph."""

import logging
from dataclasses import dataclass
from typing import Annotated

from pydantic_graph import BaseNode, Edge, End, GraphRunContext

from agent_system.adapters.outbound.fsm.state import (
    AgentDependencies,
    WorkflowResult,
    WorkflowState,
)

logger = logging.getLogger(__name__)


@dataclass
class ReceiveInput(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Initial node that receives user input and prepares the workflow."""

    user_input: str

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "AnalyzeIntent":
        """Process incoming user input."""
        await ctx.deps.emit_event("node_start", "ReceiveInput", "Receiving user input...")
        
        ctx.state.user_input = self.user_input
        ctx.state.is_complete = False
        ctx.state.error = None
        
        await ctx.deps.emit_event("node_complete", "ReceiveInput", "Input received", {"input_length": len(self.user_input)})
        return AnalyzeIntent()


@dataclass
class AnalyzeIntent(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Analyze user intent from the input message using LLM."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "UpdateKnowledge":
        """Extract intent and entities from user input using the intent agent."""
        from agent_system.domain.value_objects import Intent, IntentType
        from agent_system.adapters.outbound.llm import create_intent_agent

        await ctx.deps.emit_event("node_start", "AnalyzeIntent", "Analyzing user intent...")

        # Build context-aware prompt for intent analysis
        history_messages = ctx.state.conversation.get_context_messages()
        if history_messages:
            recent_context = "\n".join([
                f"{m.role.value}: {m.content.text[:200]}"
                for m in history_messages[-5:]
            ])
            prompt = f"""Recent conversation:
{recent_context}

Current message to analyze: {ctx.state.user_input}

Analyze the intent of the current message in context of the conversation."""
        else:
            prompt = ctx.state.user_input

        logger.info("=" * 80)
        logger.info("🎯 ANALYZE INTENT - CONTEXT FED TO INTENT AGENT")
        logger.info("=" * 80)
        logger.info(f"User ID: {ctx.state.user.id}")
        logger.info(f"Conversation ID: {ctx.state.conversation.id}")
        logger.info(f"User Input: {ctx.state.user_input}")
        logger.info(f"Conversation History Messages: {len(history_messages) if history_messages else 0}")
        if history_messages:
            logger.info("Recent Context (last 5 messages):")
            for m in history_messages[-5:]:
                logger.info(f"  {m.role.value}: {m.content.text[:100]}...")
        logger.info("-" * 40)
        logger.info("FULL INTENT ANALYSIS PROMPT:")
        logger.info(prompt)
        logger.info("=" * 80)

        result = None
        last_error: Exception | None = None

        for model, label in [
            (ctx.deps.default_model, "primary"),
            (getattr(ctx.deps, "fallback_model", "openai:gpt-5-mini-2025-08-07"), "fallback"),
        ]:
            try:
                agent = create_intent_agent(model, ctx.deps.openai_api_key)
                result = await agent.run(prompt)
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "Intent analysis with %s model failed: %s: %s",
                    label,
                    type(e).__name__,
                    e,
                )

        if result is not None:
            # Log and apply LLM result
            logger.info("=" * 80)
            logger.info("🎯 INTENT ANALYSIS RESULT")
            logger.info("=" * 80)
            logger.info(f"Intent Type: {result.output.intent_type}")
            logger.info(f"Description: {result.output.description}")
            logger.info(f"Confidence: {result.output.confidence}")
            logger.info(f"Entities: {result.output.entities}")
            logger.info(f"Requires Planning: {result.output.requires_planning}")
            logger.info(f"Is About Assistant: {result.output.is_about_assistant}")
            logger.info(f"Suggested Tool: {result.output.suggested_tool}")
            logger.info(f"Tool Input: {result.output.tool_input}")
            logger.info("=" * 80)

            intent_type_map = {
                "question": IntentType.QUESTION,
                "task": IntentType.TASK,
                "exploration": IntentType.EXPLORATION,
                "clarification": IntentType.CLARIFICATION,
                "feedback": IntentType.FEEDBACK,
                "command": IntentType.COMMAND,
                "meta": IntentType.META,
            }

            intent_type = intent_type_map.get(
                result.output.intent_type.lower(),
                IntentType.EXPLORATION,
            )

            ctx.state.intent = Intent(
                intent_type=intent_type,
                description=result.output.description,
                confidence=result.output.confidence,
                entities=result.output.entities,
            )

            ctx.state.entities = result.output.entities
            ctx.state.plan_needed = result.output.requires_planning
            ctx.state.is_about_assistant = result.output.is_about_assistant

            if result.output.suggested_tool:
                ctx.state.requires_tool = True
                ctx.state.tool_name = result.output.suggested_tool
                ctx.state.tool_input = result.output.tool_input

            await ctx.deps.emit_event(
                "node_complete",
                "AnalyzeIntent",
                f"Intent: {ctx.state.intent.intent_type.value}",
                {
                    "intent_type": ctx.state.intent.intent_type.value,
                    "confidence": ctx.state.intent.confidence,
                    "entities": ctx.state.entities,
                    "is_about_assistant": ctx.state.is_about_assistant,
                    "suggested_tool": result.output.suggested_tool,
                },
            )
        else:
            # Heuristic fallback when both models fail
            logger.error(
                "Intent analysis failed with primary and fallback models: %s: %s",
                type(last_error).__name__ if last_error else "Unknown",
                last_error,
            )
            user_input_lower = ctx.state.user_input.lower().strip()

            if any(q in user_input_lower for q in ["what", "how", "why", "when", "where", "?"]):
                intent_type = IntentType.QUESTION
            elif any(cmd in user_input_lower for cmd in ["create", "make", "build", "write", "implement"]):
                intent_type = IntentType.TASK
                ctx.state.plan_needed = True
            elif any(fb in user_input_lower for fb in ["thanks", "good", "great", "bad", "wrong"]):
                intent_type = IntentType.FEEDBACK
            else:
                intent_type = IntentType.EXPLORATION

            entities: list[str] = []
            suggested_tool: str | None = None
            tool_input_val: str | None = None

            # "Tell me a joke about X" / "Tell me a story about X" -> recall about entity for context
            for prefix in ["tell me a joke about", "tell me a story about", "tell me about", "what do you know about"]:
                if prefix in user_input_lower:
                    rest = user_input_lower.split(prefix, 1)[-1].strip().rstrip(".!?")
                    if rest and len(rest) < 100:
                        words = [w for w in rest.split() if w.lower() not in ("the", "a", "an")]
                        if words:
                            # Use last meaningful word as entity; full rest as tool input
                            entities = [words[-1]]
                            suggested_tool = "recall_about_topic"
                            tool_input_val = rest
                            break

            ctx.state.intent = Intent(
                intent_type=intent_type,
                description=ctx.state.user_input[:100],
                confidence=0.6,
                entities=entities,
            )
            ctx.state.entities = entities
            if suggested_tool:
                ctx.state.requires_tool = True
                ctx.state.tool_name = suggested_tool
                ctx.state.tool_input = tool_input_val

            await ctx.deps.emit_event(
                "node_complete",
                "AnalyzeIntent",
                f"Intent (fallback): {intent_type.value}",
                {
                    "intent_type": intent_type.value,
                    "confidence": 0.6,
                    "fallback": True,
                    "suggested_tool": suggested_tool,
                },
            )
        
        return UpdateKnowledge()


@dataclass
class UpdateKnowledge(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Update the knowledge graph with new information."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "CheckPlan":
        """Store extracted information in the knowledge graph."""
        # If knowledge graph is available, record the interaction
        if ctx.deps.knowledge_graph_port and ctx.state.intent:
            await ctx.deps.emit_event("node_start", "UpdateKnowledge", "Updating knowledge graph...")
            try:
                await ctx.deps.knowledge_graph_port.record_interaction(
                    user_id=ctx.state.user.id,
                    conversation_id=str(ctx.state.conversation.id),
                    summary=ctx.state.user_input[:200],
                    intents=[ctx.state.intent.intent_type.value],
                    entities=ctx.state.entities,
                    tools_used=[],
                    user_label=ctx.state.user.email,
                )
                await ctx.deps.emit_event("node_complete", "UpdateKnowledge", "Knowledge updated")
            except Exception as e:
                # Knowledge graph errors shouldn't break the workflow
                print(f"Knowledge graph error: {e}")
                await ctx.deps.emit_event("node_complete", "UpdateKnowledge", f"Knowledge update skipped (error)")
        else:
            await ctx.deps.emit_event("node_skipped", "UpdateKnowledge", "No knowledge graph configured")
        
        return CheckPlan()


@dataclass
class CheckPlan(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Check if there's an active plan or if one needs to be created."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> Annotated["CreatePlan", Edge(label="no active plan")] | Annotated["ExecutePlan", Edge(label="has plan")]:
        """Determine if plan creation or execution is needed."""
        from agent_system.domain.value_objects import IntentType

        await ctx.deps.emit_event("node_start", "CheckPlan", "Checking for active plans...")

        # Check for active plan
        if ctx.state.conversation.active_plan_id:
            plan = await ctx.deps.plan_repository.get(ctx.state.conversation.active_plan_id)
            if plan and plan.is_active:
                ctx.state.current_plan = plan
                await ctx.deps.emit_event("node_complete", "CheckPlan", "Found active plan", {"plan_id": str(plan.id)})
                return ExecutePlan()

        # Determine if a new plan is needed based on intent analysis
        if ctx.state.plan_needed or (ctx.state.intent and ctx.state.intent.intent_type == IntentType.TASK):
            # Enable ReAct mode for task intents - will use step-by-step reasoning
            ctx.state.react_mode = True
            ctx.state.step_results = []
            ctx.state.current_step_index = 0
            await ctx.deps.emit_event("node_complete", "CheckPlan", "Plan creation needed (ReAct mode enabled)")
            return CreatePlan()

        # No plan needed, go directly to response
        await ctx.deps.emit_event("node_complete", "CheckPlan", "No plan needed")
        # Skip CreatePlan
        await ctx.deps.emit_event("node_skipped", "CreatePlan", "Not a task intent")
        return ExecutePlan()


@dataclass
class CreatePlan(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Create a new plan for the user's task using LLM."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "ExecutePlan":
        """Create a plan using the planning agent."""
        from agent_system.domain.entities import Plan
        from agent_system.domain.value_objects import PlanGoal, PlanStep
        from agent_system.adapters.outbound.llm import create_planning_agent, create_react_planning_agent
        
        await ctx.deps.emit_event("node_start", "CreatePlan", "Creating plan for task...")
        
        try:
            # Use ReAct planning agent if in react_mode, otherwise standard planning
            if ctx.state.react_mode:
                # ENTITY CONTEXT INJECTION: Look up any named entities BEFORE planning
                # This ensures the planner knows Zane is a dog, Sarah is a spouse, etc.
                entity_context = ""
                logger.info(f"Entity lookup check: entities={ctx.state.entities}, has_kg_port={ctx.deps.knowledge_graph_port is not None}")
                if ctx.state.entities and ctx.deps.knowledge_graph_port:
                    entity_info_parts = []
                    
                    # Extract potential names from entities (handle "Zane's birthday" -> "Zane")
                    processed_entities = []
                    for entity_name in ctx.state.entities[:5]:
                        # If entity contains possessive, extract the name part
                        if "'s " in entity_name or "'s " in entity_name:
                            name_part = entity_name.split("'")[0].strip()
                            if name_part and len(name_part) > 1:
                                processed_entities.append(name_part)
                        # Also try the first word if it's capitalized (handles "Zane birthday")
                        words = entity_name.split()
                        if words and words[0][0].isupper() and len(words[0]) > 1:
                            processed_entities.append(words[0])
                        # Keep original too
                        processed_entities.append(entity_name)
                    
                    # Deduplicate
                    seen = set()
                    unique_entities = []
                    for e in processed_entities:
                        e_lower = e.lower().strip()
                        if e_lower not in seen and len(e_lower) > 1:
                            seen.add(e_lower)
                            unique_entities.append(e)
                    
                    logger.info(f"Processing {len(unique_entities)} unique entities: {unique_entities}")
                    for entity_name in unique_entities[:8]:
                        # Skip common words and phrases
                        if entity_name.lower() in ["birthday", "today", "tomorrow", "party", "the", "a", "an"]:
                            logger.debug(f"Skipping common word: {entity_name}")
                            continue
                        
                        logger.info(f"Looking up entity: '{entity_name}'")
                        try:
                            found_info = False
                            
                            # CRITICAL: Check knowledge graph FIRST - it has the most reliable info
                            # KnowledgeNodes contain facts like "User has a dog named Zane"
                            # This is more reliable than typed nodes which can be misclassified
                            logger.info(f"Searching knowledge graph for '{entity_name}'...")
                            recall_result = await ctx.deps.knowledge_graph_port.recall_about_topic(
                                ctx.state.user.id,
                                entity_name,
                                limit=5
                            )
                            if recall_result:
                                # Extract text snippets - log what we're sending to LLM
                                snippets = [r.get("content", "") for r in recall_result if r.get("content")]
                                source_types = [r.get("source_type", "unknown") for r in recall_result]
                                if snippets:
                                    logger.info(f"Found {len(snippets)} mentions of '{entity_name}' (sources: {source_types})")
                                    for i, snip in enumerate(snippets[:3]):
                                        logger.info(f"  Snippet {i+1}: {snip[:100]}...")
                                    
                                    # Use LLM to detect entity type from snippets
                                    from agent_system.adapters.outbound.llm.knowledge_extractor import detect_entity_type
                                    
                                    entity_type_result = await detect_entity_type(
                                        entity_name=entity_name,
                                        text_snippets=snippets,
                                        api_key=ctx.deps.openai_api_key,
                                    )
                                    
                                    if entity_type_result.entity_type == "pet":
                                        species = entity_type_result.species or "pet"
                                        info = f"'{entity_name}' is the user's {species}"
                                        if entity_type_result.description:
                                            info += f" ({entity_type_result.description})"
                                        entity_info_parts.append(info)
                                        logger.info(f"Entity type detected (KG): {entity_name} -> {species} (confidence: {entity_type_result.confidence})")
                                        found_info = True
                                    elif entity_type_result.entity_type == "person":
                                        rel = entity_type_result.relationship or "known person"
                                        info = f"'{entity_name}' is the user's {rel}"
                                        if entity_type_result.description:
                                            info += f" ({entity_type_result.description})"
                                        entity_info_parts.append(info)
                                        logger.info(f"Entity type detected (KG): {entity_name} -> {rel} (confidence: {entity_type_result.confidence})")
                                        found_info = True
                                    elif entity_type_result.entity_type == "location":
                                        info = f"'{entity_name}' is a location/place"
                                        if entity_type_result.description:
                                            info += f" ({entity_type_result.description})"
                                        entity_info_parts.append(info)
                                        logger.info(f"Entity type detected (KG): {entity_name} -> location (confidence: {entity_type_result.confidence})")
                                        found_info = True
                                    else:
                                        # Unknown type - just include raw snippets
                                        snippet_summary = snippets[0][:150] if snippets else ""
                                        if snippet_summary:
                                            info = f"About '{entity_name}': {snippet_summary}"
                                            entity_info_parts.append(info)
                                            logger.info(f"Entity type unknown for '{entity_name}', using raw snippet")
                                            found_info = True
                            
                            # Fallback: Check typed nodes only if knowledge graph didn't find anything
                            if not found_info:
                                logger.info(f"No knowledge graph info for '{entity_name}', checking typed nodes...")
                                # Check if it's a pet
                                pets = await ctx.deps.knowledge_graph_port.list_pets(ctx.state.user.id)
                                for pet in (pets or []):
                                    pet_name = pet.get("name", "").lower()
                                    if entity_name.lower() in pet_name or pet_name in entity_name.lower():
                                        species = pet.get("species", "pet")
                                        breed = pet.get("breed", "")
                                        info = f"'{entity_name}' is the user's {species}"
                                        if breed:
                                            info += f" ({breed})"
                                        entity_info_parts.append(info)
                                        logger.info(f"Entity lookup (PetNode): {entity_name} -> {species}")
                                        found_info = True
                                        break
                                
                                # Check if it's a person
                                if not found_info:
                                    people = await ctx.deps.knowledge_graph_port.list_known_people(ctx.state.user.id)
                                    for person in (people or []):
                                        person_name = person.get("name", "").lower()
                                        if entity_name.lower() in person_name or person_name in entity_name.lower():
                                            rel = person.get("relationship_type", "known person")
                                            info = f"'{entity_name}' is the user's {rel}"
                                            entity_info_parts.append(info)
                                            logger.info(f"Entity lookup (PersonNode): {entity_name} -> {rel}")
                                            found_info = True
                                            break
                        except Exception as entity_err:
                            logger.warning(f"Entity lookup failed for {entity_name}: {entity_err}")
                    
                    if entity_info_parts:
                        entity_context = "\n\nIMPORTANT ENTITY CONTEXT (use this when planning):\n" + "\n".join(f"- {p}" for p in entity_info_parts)
                        logger.info(f"Injecting entity context into planning: {entity_context}")
                
                # Verbose logging of ReAct planning
                logger.info("=" * 80)
                logger.info("📋 REACT PLANNING - CONTEXT FED TO PLANNING AGENT")
                logger.info("=" * 80)
                logger.info(f"User ID: {ctx.state.user.id}")
                logger.info(f"Conversation ID: {ctx.state.conversation.id}")
                logger.info(f"ReAct Mode: {ctx.state.react_mode}")
                logger.info(f"Intent Type: {ctx.state.intent.intent_type if ctx.state.intent else 'None'}")
                logger.info(f"User Input (to be broken into steps): {ctx.state.user_input}")
                if entity_context:
                    logger.info(f"Entity Context: {entity_context}")
                logger.info("=" * 80)
                
                # Build the planning prompt with entity context
                planning_prompt = ctx.state.user_input
                if entity_context:
                    planning_prompt = f"{ctx.state.user_input}{entity_context}"
                
                agent = create_react_planning_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                result = await agent.run(planning_prompt)
                
                # Log the generated plan
                logger.info("=" * 80)
                logger.info("📋 REACT PLAN GENERATED")
                logger.info("=" * 80)
                logger.info(f"Goal: {result.output.goal_description}")
                logger.info(f"Reasoning Approach: {result.output.reasoning_approach}")
                logger.info(f"Complexity: {result.output.estimated_complexity}")
                logger.info(f"Success Criteria: {result.output.success_criteria}")
                logger.info(f"Steps ({len(result.output.steps)}):")
                for i, step in enumerate(result.output.steps):
                    logger.info(f"  {i+1}. {step.description}")
                    if step.tool_required:
                        logger.info(f"     Tool Required: {step.tool_required}")
                logger.info("=" * 80)
                
                goal = PlanGoal(
                    description=result.output.goal_description,
                    success_criteria=result.output.success_criteria,
                    context={
                        "complexity": result.output.estimated_complexity,
                        "reasoning_approach": result.output.reasoning_approach,
                    },
                )
                
                steps = [
                    PlanStep(
                        description=step.description,
                        order=i,
                        tool_required=step.tool_required,
                        dependencies=step.dependencies,
                    )
                    for i, step in enumerate(result.output.steps)
                ]
                
                # Emit the reasoning approach as part of the plan
                await ctx.deps.emit_event("react_plan", "CreatePlan", result.output.reasoning_approach, {
                    "steps": [s.description for s in steps],
                    "total_steps": len(steps),
                })
            else:
                # Standard planning
                agent = create_planning_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                result = await agent.run(ctx.state.user_input)
                
                goal = PlanGoal(
                    description=result.output.goal_description,
                    success_criteria=result.output.success_criteria,
                    context={"complexity": result.output.estimated_complexity},
                )
                
                steps = [
                    PlanStep(
                        description=step.description,
                        order=i,
                        tool_required=step.tool_required,
                        dependencies=step.dependencies,
                    )
                    for i, step in enumerate(result.output.steps)
                ]
            
        except Exception as e:
            # Fallback to simple plan if LLM fails
            logger.error(f"Planning LLM call failed: {type(e).__name__}: {e}")
            goal = PlanGoal(
                description=ctx.state.user_input,
                success_criteria=["Task completed successfully"],
                context={},
            )
            
            steps = [
                PlanStep(description="Understand the core question", order=0),
                PlanStep(description="Analyze key components", order=1),
                PlanStep(description="Formulate comprehensive guidance", order=2),
            ]
        
        plan = Plan.create(
            user_id=ctx.state.user.id,
            conversation_id=ctx.state.conversation.id,
            goal=goal,
            steps=steps,
        ).activate()
        
        # Save the plan
        await ctx.deps.plan_repository.save(plan)
        
        # Update conversation with active plan
        ctx.state.conversation = ctx.state.conversation.set_active_plan(plan.id)
        await ctx.deps.conversation_repository.update(ctx.state.conversation)
        
        ctx.state.current_plan = plan
        await ctx.deps.emit_event("node_complete", "CreatePlan", f"Plan created with {len(steps)} steps", {
            "goal": goal.description[:100],
            "step_count": len(steps),
        })
        return ExecutePlan()


@dataclass
class ExecutePlan(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Execute the current plan step or determine if tools are needed."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> Annotated["SelectTool", Edge(label="needs tool")] | Annotated["GenerateResponse", Edge(label="no tool needed")]:
        """Check if tool is needed (determined by LLM in AnalyzeIntent) or proceed to response."""
        await ctx.deps.emit_event("node_start", "ExecutePlan", "Executing plan steps...")
        
        # ReAct mode: Execute each plan step with visible reasoning
        if ctx.state.react_mode and ctx.state.current_plan:
            from agent_system.adapters.outbound.llm import create_step_execution_agent
            
            steps = ctx.state.current_plan.steps
            total_steps = len(steps)
            
            # Execute each step that hasn't been executed yet
            while ctx.state.current_step_index < total_steps:
                step = steps[ctx.state.current_step_index]
                step_num = ctx.state.current_step_index + 1
                
                await ctx.deps.emit_event(
                    "react_step_start", 
                    f"Step {step_num}/{total_steps}", 
                    step.step.description,
                    {"step_index": ctx.state.current_step_index, "total_steps": total_steps}
                )
                
                try:
                    # Create prompt for this specific step
                    step_prompt = f"""Original question: {ctx.state.user_input}

You are now executing Step {step_num} of {total_steps}: "{step.step.description}"

Previous step results:
{self._format_previous_steps(ctx.state.step_results) if ctx.state.step_results else "This is the first step."}

Execute this step by providing your Thought, Action, and Observation.
Focus ONLY on this specific step - not the entire question."""

                    # Verbose logging of step execution
                    logger.info("=" * 80)
                    logger.info(f"🔄 REACT STEP {step_num}/{total_steps} - CONTEXT FED TO STEP AGENT")
                    logger.info("=" * 80)
                    logger.info(f"User ID: {ctx.state.user.id}")
                    logger.info(f"Step Description: {step.step.description}")
                    logger.info(f"Previous Steps Completed: {len(ctx.state.step_results)}")
                    if ctx.state.step_results:
                        logger.info("Previous Step Observations:")
                        for prev in ctx.state.step_results:
                            logger.info(f"  - Step {prev['step_num']}: {prev['observation'][:80]}...")
                    logger.info("-" * 40)
                    logger.info("FULL STEP PROMPT:")
                    logger.info(step_prompt)
                    logger.info("=" * 80)

                    # Run step execution agent
                    agent = create_step_execution_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                    result = await agent.run(step_prompt)
                    
                    # Store step result
                    step_result = {
                        "step_num": step_num,
                        "step_description": step.step.description,
                        "thought": result.output.thought,
                        "action": result.output.action,
                        "observation": result.output.observation,
                        "needs_tool": result.output.needs_tool,
                        "tool_suggestion": result.output.tool_suggestion,
                    }
                    ctx.state.step_results.append(step_result)
                    
                    # Emit step completion event with reasoning trace
                    await ctx.deps.emit_event(
                        "react_step_complete",
                        f"Step {step_num}/{total_steps}",
                        result.output.observation[:200],
                        {
                            "thought": result.output.thought,
                            "action": result.output.action,
                            "observation": result.output.observation,
                            "needs_tool": result.output.needs_tool,
                        }
                    )
                    
                    # If step needs a tool, pause and use it
                    if result.output.needs_tool and result.output.tool_suggestion:
                        ctx.state.requires_tool = True
                        ctx.state.tool_name = result.output.tool_suggestion
                        ctx.state.tool_input = step.step.description
                        ctx.state.current_step_index += 1  # Move to next step after tool
                        await ctx.deps.emit_event("node_complete", "ExecutePlan", f"Step {step_num} needs tool: {result.output.tool_suggestion}")
                        return SelectTool()
                    
                except Exception as e:
                    logger.error(f"Step {step_num} execution failed: {type(e).__name__}: {e}")
                    # Add a fallback result
                    ctx.state.step_results.append({
                        "step_num": step_num,
                        "step_description": step.step.description,
                        "thought": f"Analyzing: {step.step.description}",
                        "action": "think",
                        "observation": f"Continuing with available knowledge about {step.step.description.lower()}",
                        "needs_tool": False,
                        "tool_suggestion": None,
                    })
                
                ctx.state.current_step_index += 1
            
            # All steps completed - go to synthesis
            await ctx.deps.emit_event("node_complete", "ExecutePlan", f"All {total_steps} steps completed, synthesizing response")
            await ctx.deps.emit_event("node_skipped", "SelectTool", "ReAct mode - tools handled in steps")
            await ctx.deps.emit_event("node_skipped", "ExecuteTool", "ReAct mode - tools handled in steps")
            await ctx.deps.emit_event("node_skipped", "EvaluateResult", "ReAct mode - proceeding to synthesis")
            return GenerateResponse()
        
        # Standard mode: Check if tool is needed (determined by LLM in AnalyzeIntent)
        if ctx.state.requires_tool and ctx.state.tool_name:
            await ctx.deps.emit_event("node_complete", "ExecutePlan", f"Tool needed: {ctx.state.tool_name}")
            return SelectTool()
        
        # Check if there's a plan with a current step that needs a tool
        if ctx.state.current_plan and ctx.state.current_plan.current_step:
            current_step = ctx.state.current_plan.current_step
            if current_step.step.tool_required:
                ctx.state.requires_tool = True
                ctx.state.tool_name = current_step.step.tool_required
                await ctx.deps.emit_event("node_complete", "ExecutePlan", f"Tool from plan: {ctx.state.tool_name}")
                return SelectTool()
        
        # No tool needed - skip tool execution nodes
        await ctx.deps.emit_event("node_complete", "ExecutePlan", "No tool needed")
        await ctx.deps.emit_event("node_skipped", "SelectTool", "No tool required")
        await ctx.deps.emit_event("node_skipped", "ExecuteTool", "No tool required")
        await ctx.deps.emit_event("node_skipped", "EvaluateResult", "No tool result to evaluate")
        return GenerateResponse()
    
    def _format_previous_steps(self, step_results: list[dict]) -> str:
        """Format previous step results for context."""
        if not step_results:
            return ""
        
        formatted = []
        for result in step_results:
            formatted.append(f"""Step {result['step_num']}: {result['step_description']}
Thought: {result['thought']}
Observation: {result['observation']}
""")
        return "\n".join(formatted)


@dataclass
class SelectTool(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Prepare tool arguments using LLM-extracted input."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "ExecuteTool":
        """Prepare tool arguments using the LLM-determined tool_input."""
        await ctx.deps.emit_event("node_start", "SelectTool", f"Preparing tool: {ctx.state.tool_name}...")
        
        tool_name = ctx.state.tool_name.strip() if ctx.state.tool_name else ""
        tool_input = ctx.state.tool_input  # LLM-extracted input from AnalyzeIntent
        
        # Build tool arguments using the LLM-provided input
        if tool_name == "web_search":
            # Use LLM-extracted search query, fallback to user input if not provided
            query = tool_input if tool_input else ctx.state.user_input
            
            # Resolve contextual references like "the brewery", "that restaurant", "this place"
            # and also extract location context from conversation history
            import re
            
            # Common cities/locations to look for
            known_locations = [
                'Houston', 'Austin', 'Dallas', 'San Antonio', 'Fort Worth',
                'New York', 'Los Angeles', 'Chicago', 'Phoenix', 'Philadelphia',
                'Denver', 'Seattle', 'Boston', 'Atlanta', 'Miami', 'Portland',
                'Montrose', 'Midtown', 'Downtown', 'Heights', 'The Woodlands',
            ]
            
            # Texas neighborhoods/areas
            houston_areas = ['Montrose', 'Midtown', 'Heights', 'River Oaks', 'EaDo', 'Downtown', 'Galleria', 'Memorial', 'The Woodlands', 'Katy', 'Sugar Land']
            
            reference_patterns = [
                (r'\bthe\s+(brewery|bar|restaurant|place|venue|location|spot|shop|store|cafe|club)\b', 1),
                (r'\bthat\s+(brewery|bar|restaurant|place|venue|location|spot|shop|store|cafe|club)\b', 1),
                (r'\bthis\s+(brewery|bar|restaurant|place|venue|location|spot|shop|store|cafe|club)\b', 1),
                (r'\bit\b', None),  # Generic "it" reference
                (r'\bthere\b', None),  # "there" reference to a place
            ]
            
            query_lower = query.lower()
            has_reference = any(re.search(pat, query_lower) for pat, _ in reference_patterns)
            
            # Search recent conversation for context
            history_messages = ctx.state.conversation.get_context_messages()
            resolved_entity = None
            resolved_location = None
            entity_type = None
            
            # Common entity patterns to look for in conversation
            entity_keywords = ['brewery', 'bar', 'restaurant', 'cafe', 'club', 'venue', 'place']
            
            # Look backwards through messages for context
            for msg in reversed(history_messages[-10:]):
                text = msg.content.text
                
                # Extract location from conversation if not already in query
                if not resolved_location:
                    for loc in known_locations:
                        if loc.lower() in text.lower() and loc.lower() not in query_lower:
                            resolved_location = loc
                            # Check if it's a Houston area - if so, also add Houston
                            if loc in houston_areas and 'houston' not in query_lower:
                                resolved_location = f"{loc} Houston"
                            break
                
                # Only resolve entity references if query has a reference
                if has_reference and not resolved_entity:
                    # Look for proper noun phrases (capitalized multi-word names)
                    proper_noun_matches = re.findall(r'(?:[A-Z][a-z]+(?:\s+(?:the\s+)?[A-Z][a-z]+)+|"([^"]+)"|\b([A-Z][a-z]+\'s)\b)', text)
                    
                    # Also look for patterns like "X Brewery", "X Bar", etc.
                    for keyword in entity_keywords:
                        pattern = rf'\b([A-Z][A-Za-z\s]+\s+{keyword})\b'
                        matches = re.findall(pattern, text, re.IGNORECASE)
                        if matches:
                            resolved_entity = matches[0].strip()
                            entity_type = keyword
                            break
                    
                    if not resolved_entity:
                        # Check for "Under the Radar" style names (proper nouns)
                        for match in proper_noun_matches:
                            if isinstance(match, tuple):
                                match = next((m for m in match if m), None)
                            if match and len(match) > 3:
                                # Skip common non-entity phrases
                                skip_phrases = {'The', 'What', 'How', 'Why', 'When', 'Where', 'Thank', 'Thanks', 'Great', 'Good', 'Nice'}
                                if match.split()[0] not in skip_phrases:
                                    resolved_entity = match.strip()
                                    break
                
                # Stop if we found both
                if resolved_entity and resolved_location:
                    break
            
            # Apply entity resolution
            if resolved_entity and has_reference:
                for pattern, group in reference_patterns:
                    if re.search(pattern, query_lower):
                        # Replace "the brewery" with the actual name
                        query = re.sub(pattern, resolved_entity, query, flags=re.IGNORECASE)
                        break
                query = query.strip()
            
            # Append location context if not already in query
            if resolved_location and resolved_location.lower() not in query.lower():
                query = f"{query} {resolved_location}"
            
            ctx.state.tool_arguments = {"query": query, "num_results": 5}
        
        elif tool_name == "calculate":
            # Use LLM-extracted mathematical expression
            if tool_input:
                # Convert ^ to ** for Python evaluation
                expr = tool_input.replace('^', '**')
                ctx.state.tool_arguments = {"expression": expr}
            else:
                # Fallback - LLM should always provide this, but just in case
                ctx.state.tool_arguments = {"expression": "0"}
        
        elif tool_name == "define_word":
            # Use LLM-extracted word
            word = tool_input if tool_input else "word"
            ctx.state.tool_arguments = {"word": word}

        elif tool_name == "search_internal_docs":
            # Search internal docs for system/how-it-works questions
            query = tool_input if tool_input else "knowledge graph semantic search memory"
            ctx.state.tool_arguments = {"query": query, "max_sections": 5}
        
        elif tool_name == "get_current_datetime":
            # Pass user_id for timezone lookup
            ctx.state.tool_arguments = {"user_id": str(ctx.state.user.id)}
        
        elif tool_name == "random_fact":
            ctx.state.tool_arguments = {}
        
        elif tool_name in ["get_user_profile", "get_conversation_history", "analyze_conversation_patterns"]:
            ctx.state.tool_arguments = {"user_id": str(ctx.state.user.id)}
        
        elif tool_name == "summarize_user_knowledge":
            # User ID is auto-injected by ExecuteTool for knowledge graph tools
            ctx.state.tool_arguments = {"user_id": str(ctx.state.user.id)}
        
        elif tool_name == "recall_about_topic":
            # Use LLM-extracted topic, user_id is auto-injected
            topic = tool_input if tool_input else "unknown"
            
            # Resolve pronouns from conversation context
            pronouns = ["his", "her", "their", "its", "he", "she", "they", "it", "him", "them"]
            topic_lower = topic.lower()
            has_pronoun = any(p in topic_lower.split() for p in pronouns)
            
            if has_pronoun:
                # Search recent conversation for names/entities to resolve pronouns
                history_messages = ctx.state.conversation.get_context_messages()
                resolved_name = None
                
                # Look backwards through messages for the most recent entity discussed
                for msg in reversed(history_messages[-10:]):  # Check last 10 messages
                    text = msg.content.text.lower()
                    # Check for common patterns like "about X", "know about X", "X is", "X's"
                    import re
                    # Look for capitalized words (proper nouns) in the context
                    words = msg.content.text.split()
                    for word in words:
                        # Check if it's a capitalized word (potential name) that's not at sentence start
                        clean_word = re.sub(r'[^\w]', '', word)
                        if clean_word and clean_word[0].isupper() and len(clean_word) > 1:
                            # Skip common non-name words
                            skip_words = {'I', 'The', 'A', 'An', 'It', 'He', 'She', 'They', 'What', 'How', 'Why', 'When', 'Where', 'Is', 'Are', 'Was', 'Were', 'Do', 'Does', 'Did', 'Can', 'Could', 'Would', 'Should', 'Will', 'Has', 'Have', 'Had', 'For', 'From', 'With', 'About', 'This', 'That', 'These', 'Those', 'My', 'Your', 'His', 'Her', 'Their', 'Its', 'And', 'Or', 'But', 'So', 'If', 'Then', 'Well', 'Just', 'Also', 'Very', 'Really', 'Actually', 'Basically'}
                            if clean_word not in skip_words:
                                resolved_name = clean_word
                                break
                    if resolved_name:
                        break
                
                if resolved_name:
                    # Replace pronoun with resolved name
                    for pronoun in pronouns:
                        topic = re.sub(rf'\b{pronoun}\b', resolved_name, topic, flags=re.IGNORECASE)
                    topic = topic.strip()
            
            ctx.state.tool_arguments = {"topic": topic, "user_id": str(ctx.state.user.id)}
        
        elif tool_name == "recall_group_topic":
            # Group topic search - requires group context
            topic = tool_input if tool_input else "unknown"
            group_id = ctx.state.group_context.get("group_id", "") if ctx.state.group_context else ""
            ctx.state.tool_arguments = {"topic": topic, "group_id": group_id}
        
        elif tool_name == "get_upcoming_events":
            # Event lookup with flexible filtering
            # Parse tool_input for: timeframe, search_query, temporal_filter, specific_date
            timeframe = "week"  # default
            search_query = None
            temporal_filter = "future"  # default
            specific_date = None
            
            if tool_input:
                input_lower = tool_input.lower().strip()
                
                # Parse timeframe
                if "today" in input_lower:
                    timeframe = "today"
                elif "tomorrow" in input_lower:
                    timeframe = "tomorrow"
                elif "week" in input_lower:
                    timeframe = "week"
                elif "month" in input_lower:
                    timeframe = "month"
                elif "all" in input_lower:
                    timeframe = "all"
                
                # Parse temporal filter
                if "past" in input_lower:
                    temporal_filter = "past"
                elif "current" in input_lower or "now" in input_lower or "happening" in input_lower:
                    temporal_filter = "current"
                elif "future" in input_lower or "upcoming" in input_lower:
                    temporal_filter = "future"
                
                # Extract search query (look for patterns like "search:haircut" or just keywords)
                import re
                # Check for explicit search: prefix
                search_match = re.search(r'search[:\s]+([^\s,]+)', input_lower)
                if search_match:
                    search_query = search_match.group(1)
                else:
                    # Check for query: prefix
                    query_match = re.search(r'query[:\s]+([^\s,]+)', input_lower)
                    if query_match:
                        search_query = query_match.group(1)
                    else:
                        # Look for quoted strings as search terms
                        quoted_match = re.search(r'"([^"]+)"', tool_input)
                        if quoted_match:
                            search_query = quoted_match.group(1)
                        else:
                            # Extract likely search keywords (nouns that aren't time-related)
                            time_words = {'today', 'tomorrow', 'week', 'month', 'all', 'past', 'current', 
                                          'future', 'upcoming', 'now', 'happening', 'events', 'schedule',
                                          'calendar', 'when', 'what', 'my', 'the', 'is', 'are', 'a', 'an'}
                            words = re.findall(r'\b[a-z]+\b', input_lower)
                            keywords = [w for w in words if w not in time_words and len(w) > 2]
                            if keywords:
                                search_query = keywords[0]  # Use first non-time keyword
                
                # Extract specific date (look for date patterns)
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', tool_input)
                if date_match:
                    specific_date = date_match.group(1)
                else:
                    # Try "Month Day" pattern
                    month_day_match = re.search(
                        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})',
                        input_lower
                    )
                    if month_day_match:
                        specific_date = f"{month_day_match.group(1).capitalize()} {month_day_match.group(2)}"
            
            group_id = ctx.state.group_context.get("group_id", "") if ctx.state.group_context else None
            ctx.state.tool_arguments = {
                "user_id": str(ctx.state.user.id),
                "timeframe": timeframe,
                "group_id": group_id,
                "search_query": search_query,
                "temporal_filter": temporal_filter,
                "specific_date": specific_date,
            }
            logger.debug(f"Event lookup args: timeframe={timeframe}, search={search_query}, temporal={temporal_filter}, date={specific_date}")
        
        elif tool_name == "get_houston_events":
            # Houston area events from htown_mania
            # Parse query and category from tool_input
            query = None
            category = None
            
            if tool_input:
                input_lower = tool_input.lower().strip()
                
                # Temporal words are NOT search queries - they're just time references
                # Don't filter events by text when user says "today", "tonight", etc.
                temporal_words = [
                    "today", "tonight", "tomorrow", "now", "this week", "this weekend",
                    "next week", "upcoming", "soon", "currently", "happening",
                    "what's on", "what's up", "going on", "events",
                ]
                is_temporal_only = any(
                    input_lower == word or input_lower.startswith(word + " ") or input_lower.endswith(" " + word)
                    for word in temporal_words
                ) or input_lower in temporal_words
                
                # Check for category keywords
                categories = ["music", "cycling", "sports", "arts", "food", "festival", "comedy", "theater", "concert"]
                for cat in categories:
                    if cat in input_lower:
                        category = cat
                        break
                
                # Use full input as query ONLY if it's a real search term, not just temporal
                if input_lower and input_lower not in categories and not is_temporal_only:
                    # Also check if it's JUST a temporal reference
                    words = input_lower.split()
                    non_temporal_words = [w for w in words if w not in temporal_words and w not in ["in", "on", "at", "the", "for", "houston"]]
                    if non_temporal_words:
                        query = tool_input
            
            ctx.state.tool_arguments = {
                "query": query,
                "category": category,
                "limit": 30,
            }
            logger.debug(f"Houston events args: query={query}, category={category}")
        
        elif tool_name == "list_pets":
            # List pets with optional species filter
            # tool_input should be species like "dog", "cat", or empty for all
            species = None
            if tool_input:
                input_lower = tool_input.lower().strip()
                if input_lower in ["dog", "dogs", "cat", "cats", "bird", "birds", "fish", "rabbit", "hamster"]:
                    # Normalize to singular
                    species = input_lower.rstrip("s")
            ctx.state.tool_arguments = {"species": species} if species else {}
            logger.debug(f"list_pets args: species={species}")
        
        elif tool_name == "get_pet_info":
            # Get specific pet info - requires name
            name = tool_input.strip() if tool_input else ""
            if not name:
                # No name provided - suggest using list_pets instead
                ctx.state.tool_arguments = {}
            else:
                ctx.state.tool_arguments = {"name": name}
            logger.debug(f"get_pet_info args: name={name}")
        
        elif tool_name == "list_known_people":
            # List known people - no arguments needed
            ctx.state.tool_arguments = {}
        
        elif tool_name == "list_locations":
            # List locations - no arguments needed  
            ctx.state.tool_arguments = {}
        
        else:
            # Unknown tool - set empty arguments to avoid errors
            ctx.state.tool_arguments = {}
            await ctx.deps.emit_event("node_warning", "SelectTool", f"Unknown tool: {tool_name}", {})
        
        await ctx.deps.emit_event("node_complete", "SelectTool", f"Tool prepared: {tool_name}", {
            "tool_name": tool_name,
            "arguments": {k: str(v)[:100] for k, v in ctx.state.tool_arguments.items()},
        })
        return ExecuteTool()


@dataclass
class ExecuteTool(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Execute the selected tool."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "EvaluateResult":
        """Execute the tool and capture the result."""
        from agent_system.adapters.outbound.llm.tools import AVAILABLE_TOOLS
        
        await ctx.deps.emit_event("node_start", "ExecuteTool", f"Executing {ctx.state.tool_name}...")
        
        tool_name = ctx.state.tool_name
        tool_args = ctx.state.tool_arguments
        
        if tool_name not in AVAILABLE_TOOLS:
            ctx.state.tool_result = f"Unknown tool: {tool_name}"
            return EvaluateResult()
        
        tool_info = AVAILABLE_TOOLS[tool_name]
        tool_func = tool_info["function"]
        
        try:
            # Add repository dependencies if needed
            if tool_info.get("requires_repos"):
                if "user_repository" in tool_func.__code__.co_varnames:
                    tool_args["user_repository"] = ctx.deps.user_repository
                if "conversation_repository" in tool_func.__code__.co_varnames:
                    tool_args["conversation_repository"] = ctx.deps.conversation_repository
            
            # Add knowledge graph port if needed
            if tool_info.get("requires_knowledge_graph"):
                if "knowledge_graph_port" in tool_func.__code__.co_varnames:
                    tool_args["knowledge_graph_port"] = ctx.deps.knowledge_graph_port
                # Auto-inject user_id for knowledge graph tools
                if "user_id" in tool_func.__code__.co_varnames and "user_id" not in tool_args:
                    tool_args["user_id"] = str(ctx.state.user.id)
            
            # Add embedding port if needed (for semantic search)
            if tool_info.get("requires_embedding"):
                if "embedding_port" in tool_func.__code__.co_varnames:
                    tool_args["embedding_port"] = ctx.deps.embedding_port
            
            # Add database session if needed (for event queries)
            if tool_info.get("requires_session"):
                from agent_system.composition_root.container import get_container
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Creating database session for tool {tool_name} with args: {list(tool_args.keys())}")
                container = await get_container()
                async with container.database.session() as session:
                    tool_args["session"] = session
                    # Auto-inject user_id for session-based tools
                    if "user_id" in tool_func.__code__.co_varnames and "user_id" not in tool_args:
                        tool_args["user_id"] = str(ctx.state.user.id)
                    logger.info(f"Executing tool {tool_name} with args: {list(tool_args.keys())}")
                    result = await tool_func(**tool_args)
                    logger.info(f"Tool {tool_name} result: success={result.success}, message={result.message[:100] if result.message else 'None'}")
            else:
                result = await tool_func(**tool_args)
            
            if result.success:
                ctx.state.tool_result = result.message
                if result.data:
                    # Format data nicely for the response
                    if isinstance(result.data, list):
                        if tool_name == "web_search":
                            formatted = "\n".join([
                                f"• {item['title']}\n  {item['snippet']}\n  URL: {item['url']}"
                                for item in result.data[:5]
                            ])
                            ctx.state.tool_result = f"Search results:\n{formatted}"
                        elif tool_name == "search_internal_docs":
                            formatted = "\n\n".join([
                                f"## {item['title']}\n{item['content']}"
                                for item in result.data
                            ])
                            ctx.state.tool_result = f"Internal documentation:\n\n{formatted}"
                        elif tool_name == "get_houston_events":
                            # Houston events: message already contains fully formatted output
                            # Don't append raw data
                            ctx.state.tool_result = result.message
                        elif tool_name == "get_upcoming_events":
                            # User's personal events: message already formatted as table
                            # Don't append raw data
                            ctx.state.tool_result = result.message
                        else:
                            ctx.state.tool_result = f"{result.message}\n{result.data}"
                    elif isinstance(result.data, dict):
                        if "fact" in result.data:
                            ctx.state.tool_result = f"🎯 {result.data['fact']}"
                        elif "result" in result.data:
                            ctx.state.tool_result = f"📊 {result.data['expression']} = {result.data['result']}"
                        elif "definitions" in result.data:
                            defs = result.data["definitions"]
                            formatted = "\n".join([
                                f"• ({d['part_of_speech']}) {d['definition']}"
                                for d in defs[:3]
                            ])
                            ctx.state.tool_result = f"📖 {result.data['word']}: {result.data.get('phonetic', '')}\n{formatted}"
                        elif "datetime" in result.data:
                            ctx.state.tool_result = f"🕐 {result.data['date']} ({result.data['day_of_week']}) at {result.data['time']}"
                        elif "formatted_summary" in result.data:
                            # Knowledge graph summary
                            ctx.state.tool_result = f"📊 Knowledge Summary:\n{result.data['formatted_summary']}\n\n{result.data.get('summary', '')}"
                        else:
                            ctx.state.tool_result = f"{result.message}"
            else:
                ctx.state.tool_result = f"Tool failed: {result.message}"
                
        except Exception as e:
            ctx.state.tool_result = f"Error executing {tool_name}: {str(e)}"
        
        await ctx.deps.emit_event("tool_result", "ExecuteTool", f"Tool completed: {tool_name}", {
            "tool_name": tool_name,
            "result_preview": ctx.state.tool_result[:200] if ctx.state.tool_result else None,
        })
        return EvaluateResult()


@dataclass
class EvaluateResult(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Evaluate the result of tool execution."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> Annotated["ExecutePlan", Edge(label="continue")] | Annotated["GenerateResponse", Edge(label="done")]:
        """Evaluate tool result and decide next step."""
        await ctx.deps.emit_event("node_start", "EvaluateResult", "Evaluating tool result...")
        
        # CRITICAL: Update the last step result with the ACTUAL tool output
        # The step_results observation was the LLM's prediction; replace with real data
        if ctx.state.step_results and ctx.state.tool_result:
            # Find and update the most recent step that used this tool
            for i in range(len(ctx.state.step_results) - 1, -1, -1):
                step = ctx.state.step_results[i]
                if step.get('needs_tool') and step.get('tool_suggestion') == ctx.state.tool_name:
                    logger.info(f"Updating step {step['step_num']} observation with actual tool result ({len(ctx.state.tool_result)} chars)")
                    ctx.state.step_results[i]['observation'] = ctx.state.tool_result
                    break
        
        # Update plan step if active
        if ctx.state.current_plan and ctx.state.current_plan.current_step:
            result = ctx.state.tool_result or "Step completed"
            ctx.state.current_plan = ctx.state.current_plan.complete_current_step(result)
            await ctx.deps.plan_repository.update(ctx.state.current_plan)
            
            # Check if more steps remain
            if not ctx.state.current_plan.is_complete:
                ctx.state.requires_tool = False
                ctx.state.tool_name = None
                ctx.state.tool_arguments = {}
                await ctx.deps.emit_event("node_complete", "EvaluateResult", "More plan steps remain")
                return ExecutePlan()
        
        # Tool executed, generate response incorporating the result
        await ctx.deps.emit_event("node_complete", "EvaluateResult", "Result accepted, generating response")
        return GenerateResponse()


@dataclass
class GenerateResponse(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Generate the final response to the user using LLM."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> "FinalizeKnowledge":
        """Generate a response using the coordinator agent."""
        from agent_system.adapters.outbound.llm import create_coordinator_agent, create_synthesis_agent
        
        await ctx.deps.emit_event("node_start", "GenerateResponse", "Generating response...")
        
        # =============================================================
        # SEMANTIC SEARCH: Retrieve related past conversations
        # =============================================================
        related_history: list[dict] = []
        try:
            if ctx.deps.knowledge_graph_port and ctx.deps.embedding_port:
                # Embed the current user input
                query_embedding = await ctx.deps.embedding_port.embed(ctx.state.user_input)
                
                # Search for semantically similar past messages
                related_history = await ctx.deps.knowledge_graph_port.semantic_search(
                    user_id=ctx.state.user.id,
                    query_embedding=query_embedding.embedding,
                    limit=25,  # Top 25 related messages for richer context
                    min_score=0.7,  # Only high-quality matches
                )
                
                # Filter out messages from the current conversation
                current_conv_id = str(ctx.state.conversation.id)
                related_history = [
                    msg for msg in related_history 
                    if msg.get("conversation_id") != current_conv_id
                ]
                
                if related_history:
                    logger.info(f"Found {len(related_history)} semantically related past messages")
                    for i, msg in enumerate(related_history[:3]):
                        logger.debug(f"  Related [{i+1}] (score={msg['score']:.2f}): {msg['content'][:80]}...")
        except Exception as e:
            logger.debug(f"Semantic search failed (non-critical): {e}")
        
        # =============================================================
        # CONTEXTUAL SUGGESTIONS: Get related entities from social graph
        # =============================================================
        contextual_suggestions: list[dict] = []
        try:
            if ctx.deps.knowledge_graph_port:
                # Extract potential entity names from user input
                # Simple extraction - look for capitalized words that might be names
                words = ctx.state.user_input.split()
                potential_entities = [
                    w.strip(",.!?") for w in words 
                    if w and w[0].isupper() and len(w) > 1
                ]
                
                if potential_entities:
                    contextual_suggestions = await ctx.deps.knowledge_graph_port.get_contextual_suggestions(
                        user_id=ctx.state.user.id,
                        mentioned_entities=potential_entities[:5],  # Limit to 5 entities
                        limit=5,
                    )
                    
                    if contextual_suggestions:
                        logger.info(f"Found {len(contextual_suggestions)} contextual suggestions from social graph")
                        for sug in contextual_suggestions[:3]:
                            logger.debug(f"  Suggestion: {sug.get('name')} ({sug.get('type')}, relevance={sug.get('relevance', 0):.2f})")
        except Exception as e:
            logger.debug(f"Contextual suggestions failed (non-critical): {e}")
        
        # ReAct mode: Synthesize step results into final response
        if ctx.state.react_mode and ctx.state.step_results:
            await ctx.deps.emit_event("react_synthesis_start", "GenerateResponse", "Synthesizing step results...")
            
            try:
                # Check if step results contain structured data that should bypass synthesis
                # This prevents LLMs from summarizing data that users need to see in full
                for result in ctx.state.step_results:
                    observation = result.get('observation', '')
                    
                    # Detect structured event listings (Houston events, etc.)
                    if '## Houston Events' in observation or '### 1. [' in observation:
                        logger.info("Detected structured event data - bypassing synthesis to preserve links")
                        ctx.state.response = f"Here's what I found:\n\n{observation}"
                        
                        await ctx.deps.emit_event("react_synthesis_complete", "GenerateResponse", "Structured data returned directly", {
                            "bypassed_synthesis": True,
                            "data_type": "event_listing",
                        })
                        await ctx.deps.emit_event("node_complete", "GenerateResponse", "Response generated (structured data bypass)", {
                            "response_length": len(ctx.state.response),
                        })
                        return End(WorkflowResult(
                            response=ctx.state.response,
                            suggestions=[],
                            knowledge_updates=[],
                        ))
                    
                    # Detect markdown tables
                    if '|' in observation and '---' in observation and observation.count('|') > 10:
                        logger.info("Detected markdown table - bypassing synthesis to preserve formatting")
                        ctx.state.response = f"Here's what I found:\n\n{observation}"
                        
                        await ctx.deps.emit_event("node_complete", "GenerateResponse", "Response generated (table bypass)", {
                            "response_length": len(ctx.state.response),
                        })
                        return End(WorkflowResult(
                            response=ctx.state.response,
                            suggestions=[],
                            knowledge_updates=[],
                        ))
                
                # Format step results for synthesis (for non-structured responses)
                steps_formatted = []
                for result in ctx.state.step_results:
                    steps_formatted.append(f"""**Step {result['step_num']}: {result['step_description']}**
Thought: {result['thought']}
Observation: {result['observation']}
""")
                
                synthesis_prompt = f"""Original question: {ctx.state.user_input}

Here are the reasoning steps that were executed:

{"".join(steps_formatted)}

Now create a helpful response following these rules:

CRITICAL: If the Observations contain STRUCTURED DATA like:
- Event listings with markdown links → INCLUDE THE FULL LISTING with all links intact
- Tables → INCLUDE the complete table
- Lists with URLs → INCLUDE all URLs exactly as provided

For event/data responses:
1. Brief intro (1-2 sentences)
2. INCLUDE THE COMPLETE TOOL OUTPUT with all formatting and links
3. Brief helpful closing

For conversational responses:
1. Flow naturally
2. Be thorough and helpful
3. Include practical guidance"""

                # Verbose logging of synthesis prompt
                logger.info("=" * 80)
                logger.info("🧠 REACT SYNTHESIS - CONTEXT FED TO SYNTHESIS AGENT")
                logger.info("=" * 80)
                logger.info(f"User ID: {ctx.state.user.id}")
                logger.info(f"Conversation ID: {ctx.state.conversation.id}")
                logger.info(f"Original Question: {ctx.state.user_input}")
                logger.info("-" * 40)
                logger.info(f"Number of ReAct Steps: {len(ctx.state.step_results)}")
                for i, step in enumerate(ctx.state.step_results):
                    logger.info(f"  Step {i+1}: {step['step_description'][:80]}...")
                    logger.info(f"    Thought: {step['thought'][:100]}...")
                    logger.info(f"    Action: {step['action']}")
                    logger.info(f"    Observation: {step['observation'][:100]}...")
                logger.info("-" * 40)
                logger.info("FULL SYNTHESIS PROMPT:")
                logger.info(synthesis_prompt)
                logger.info("=" * 80)

                # Check if we have an event callback for streaming
                has_streaming_callback = ctx.deps.event_callback is not None
                
                if has_streaming_callback:
                    # Use streaming synthesis agent
                    from agent_system.adapters.outbound.llm import create_streaming_synthesis_agent
                    streaming_agent = create_streaming_synthesis_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                    
                    try:
                        async with streaming_agent.run_stream(synthesis_prompt) as stream:
                            accumulated_text = ""
                            async for text_chunk in stream.stream_text(delta=True):
                                accumulated_text += text_chunk
                                await ctx.deps.emit_event("response_chunk", "GenerateResponse", text_chunk, {
                                    "accumulated_length": len(accumulated_text),
                                })
                            
                            ctx.state.response = await stream.get_output()
                            logger.info(f"Streaming synthesis completed, length: {len(ctx.state.response)}")
                    except Exception as stream_err:
                        logger.warning(f"ReAct synthesis streaming failed, falling back: {stream_err}")
                        agent = create_synthesis_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                        result = await agent.run(synthesis_prompt)
                        ctx.state.response = result.output.synthesized_response
                        
                        if result.output.follow_up_suggestions:
                            from agent_system.domain.value_objects import Suggestion
                            ctx.state.suggestions = [
                                Suggestion(
                                    title=s[:50],
                                    description=s,
                                    relevance_score=0.8,
                                    based_on=[],
                                    action_type="follow_up",
                                )
                                for s in result.output.follow_up_suggestions[:3]
                            ]
                else:
                    # Non-streaming: use structured synthesis agent
                    agent = create_synthesis_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                    result = await agent.run(synthesis_prompt)
                    ctx.state.response = result.output.synthesized_response
                    
                    if result.output.follow_up_suggestions:
                        from agent_system.domain.value_objects import Suggestion
                        ctx.state.suggestions = [
                            Suggestion(
                                title=s[:50],
                                description=s,
                                relevance_score=0.8,
                                based_on=[],
                                action_type="follow_up",
                            )
                            for s in result.output.follow_up_suggestions[:3]
                        ]
                
                await ctx.deps.emit_event("react_synthesis_complete", "GenerateResponse", "Response synthesized", {
                    "response_length": len(ctx.state.response),
                })
                
                await ctx.deps.emit_event("node_complete", "GenerateResponse", "ReAct response generated", {
                    "response_length": len(ctx.state.response),
                    "steps_used": len(ctx.state.step_results),
                })
                return FinalizeKnowledge()
                
            except Exception as e:
                logger.error(f"ReAct synthesis failed: {type(e).__name__}: {e}")
                # Fall through to standard response generation
                await ctx.deps.emit_event("react_synthesis_error", "GenerateResponse", f"Synthesis failed, using standard response: {e}")
        
        # Standard response generation (non-ReAct mode or fallback)
        
        # BYPASS: Check if tool_result contains structured data that should be returned directly
        # This prevents LLMs from summarizing event listings, tables, etc.
        if ctx.state.tool_result:
            tool_result = ctx.state.tool_result
            
            # Detect structured event listings
            if '## Houston Events' in tool_result or ('### 1. [' in tool_result and 'https://' in tool_result):
                logger.info(f"Detected structured event data in tool_result - bypassing LLM synthesis ({len(tool_result)} chars)")
                ctx.state.response = f"Here's what I found:\n\n{tool_result}"
                
                await ctx.deps.emit_event("node_complete", "GenerateResponse", "Structured event data returned directly", {
                    "response_length": len(ctx.state.response),
                    "bypassed_synthesis": True,
                })
                return FinalizeKnowledge()
            
            # Detect markdown tables with significant data
            if '|' in tool_result and '---' in tool_result and tool_result.count('|') > 15:
                logger.info(f"Detected markdown table in tool_result - bypassing LLM synthesis ({len(tool_result)} chars)")
                ctx.state.response = f"Here's what I found:\n\n{tool_result}"
                
                await ctx.deps.emit_event("node_complete", "GenerateResponse", "Table data returned directly", {
                    "response_length": len(ctx.state.response),
                    "bypassed_synthesis": True,
                })
                return FinalizeKnowledge()
        
        # Build the conversation as a natural dialogue for the LLM
        prompt_parts = []
        
        # Check if user is asking about assistant capabilities (detected by intent LLM)
        is_meta_question = ctx.state.is_about_assistant
        
        if is_meta_question:
            # User is asking about the agent itself - provide capability info
            prompt_parts.append("""[Your Capabilities]
You are an AI assistant with the following tools and abilities:

TOOLS AVAILABLE:
- Web Search: Search the internet for current information
- Calculator: Perform mathematical calculations  
- Word Definitions: Look up word meanings and definitions
- Random Facts: Share interesting trivia and facts
- Date/Time: Get current date and time information
- User Profile: Access and update user preferences
- Conversation History: Review past conversations
- Analytics: Analyze conversation patterns

GENERAL ABILITIES:
- Natural conversation with memory across sessions
- Learning user preferences and interests over time
- Creating plans for complex multi-step tasks
- Providing thoughtful, engaging responses

When asked about your capabilities, describe these clearly and offer to demonstrate any of them.
""")
        else:
            # Regular conversation - only include relevant user context
            # Check if learned patterns are relevant to current message
            if ctx.state.user.learned_patterns:
                user_input_lower = ctx.state.user_input.lower()
                relevant_patterns = []
                for p in ctx.state.user.learned_patterns[:5]:
                    # Only include if pattern keywords appear in recent conversation
                    pattern_words = set(p.description.lower().split())
                    if any(word in user_input_lower for word in pattern_words if len(word) > 3):
                        relevant_patterns.append(p.description)
                
                if relevant_patterns:
                    prompt_parts.append(f"[Relevant User Context]\n{'; '.join(relevant_patterns)}\n")
        
        # Include semantically related past conversations (from embedding search)
        if related_history:
            prompt_parts.append("[Related Past Discussions]")
            prompt_parts.append("The user has discussed similar topics before:")
            for msg in related_history[:10]:  # Top 10 most relevant for richer context
                role = "User" if msg.get("role") == "user" else "You (previously)"
                content = msg.get("content", "")[:300]  # Truncate long messages
                score = msg.get("score", 0)
                prompt_parts.append(f"  - {role}: \"{content}...\" (relevance: {score:.0%})")
            prompt_parts.append("")  # Empty line separator
        
        # Present the full conversation history as a natural dialogue
        # Include tool usage so we can faithfully answer "what did you do?" questions
        history_messages = ctx.state.conversation.get_context_messages()
        if history_messages:
            prompt_parts.append("[This Conversation So Far]")
            for msg in history_messages:
                role = "User" if msg.role.value == "user" else "You"
                content = msg.content.text
                # Include tool usage context for assistant messages
                if msg.role.value == "assistant" and msg.tool_calls:
                    tool_names = [tc.tool_name for tc in msg.tool_calls]
                    prompt_parts.append(f"{role} (used tools: {', '.join(tool_names)}): {content}")
                else:
                    prompt_parts.append(f"{role}: {content}")
            prompt_parts.append("")  # Empty line before current message
        
        # Add tool result naturally if one was used in THIS exchange
        if ctx.state.tool_result and ctx.state.tool_name:
            prompt_parts.append(f"[Tool Used in This Response: {ctx.state.tool_name}]")
            prompt_parts.append(f"Result: {ctx.state.tool_result}\n")
        
        # Current message to respond to
        prompt_parts.append(f"[Current User Message]\nUser: {ctx.state.user_input}")
        
        # Instructions - check if tool result contains a table
        has_table = ctx.state.tool_result and "|" in ctx.state.tool_result and "---" in ctx.state.tool_result
        
        table_instruction = ""
        if has_table:
            table_instruction = """
**CRITICAL - MARKDOWN TABLE REQUIREMENT:**
The tool result above contains a MARKDOWN TABLE. You MUST:
1. Include the EXACT table in your response (copy it verbatim)
2. Add a brief intro BEFORE the table (1-2 sentences)
3. Add commentary AFTER the table (2-3 sentences)
4. DO NOT paraphrase the table data into prose - SHOW THE TABLE

"""
        
        prompt_parts.append(f"""
[Your Task]
Continue this conversation with a SUBSTANTIVE, thoughtful response. Requirements:
{table_instruction}
1. DEPTH: Give a full response (3-6 sentences minimum), not a brief one-liner
2. CONTEXT: Track who/what is being discussed - resolve "he/she/it" from the conversation
3. ENGAGEMENT: Share your thoughts, reactions, and relevant observations  
4. FLOW: Weave in natural follow-up questions rather than just asking one at the end
5. NO Q&A: Don't just ask a question back - actually engage with what they shared
6. TOOL AWARENESS: If the user asks "how did you know that?" or "what did you do?", reference the tools you used (shown in parentheses in the history)

If they're telling a story, react to it meaningfully. If they shared something surprising, acknowledge the impact. Add relevant context or gentle insights when appropriate.

When the user asks about your process or how you arrived at an answer, explain the tools you used (e.g., "I used the calculator tool to compute 1+3-4=0").

Respond as "You" continuing the conversation:""")
        
        prompt = "\n".join(prompt_parts)

        # Verbose logging of FULL assembled context
        logger.info("=" * 80)
        logger.info("📝 ASSEMBLED CONTEXT - FULL DETAILS")
        logger.info("=" * 80)
        
        # 1. User Context
        logger.info("┌─── USER CONTEXT ───")
        logger.info(f"│ User ID: {ctx.state.user.id}")
        logger.info(f"│ User Email: {ctx.state.user.email}")
        logger.info(f"│ Is Superuser: {ctx.state.user.is_superuser}")
        logger.info(f"│ Is Active: {ctx.state.user.is_active}")
        logger.info("└────────────────────")
        
        # 2. Conversation Context  
        logger.info("┌─── CONVERSATION CONTEXT ───")
        logger.info(f"│ Conversation ID: {ctx.state.conversation.id}")
        logger.info(f"│ Title: {ctx.state.conversation.metadata.title or '(untitled)'}")
        logger.info(f"│ Active Plan ID: {ctx.state.conversation.active_plan_id or 'None'}")
        logger.info(f"│ Total Messages: {len(ctx.state.conversation.messages)}")
        logger.info("└────────────────────────────")
        
        # 3. Full Conversation History
        logger.info("┌─── CONVERSATION HISTORY (PostgreSQL) ───")
        if history_messages:
            for i, msg in enumerate(history_messages):
                role = "USER" if msg.role.value == "user" else "ASSISTANT"
                content_preview = msg.content.text[:150].replace('\n', ' ')
                tool_info = ""
                if msg.tool_calls:
                    tool_info = f" [tools: {', '.join(tc.tool_name for tc in msg.tool_calls)}]"
                logger.info(f"│ [{i+1}] {role}{tool_info}: {content_preview}...")
        else:
            logger.info("│ (No prior messages)")
        logger.info("└─────────────────────────────────────────")
        
        # 4. User Learned Patterns (Knowledge Graph)
        logger.info("┌─── USER LEARNED PATTERNS (Neo4j Knowledge) ───")
        if ctx.state.user.learned_patterns:
            logger.info(f"│ Total Patterns: {len(ctx.state.user.learned_patterns)}")
            for i, p in enumerate(ctx.state.user.learned_patterns[:10]):  # Show top 10
                logger.info(f"│ [{i+1}] {p.description}")
            if len(ctx.state.user.learned_patterns) > 10:
                logger.info(f"│ ... and {len(ctx.state.user.learned_patterns) - 10} more patterns")
        else:
            logger.info("│ (No learned patterns)")
        logger.info("└────────────────────────────────────────────────")
        
        # 5. Related History (Semantic Search via Embeddings)
        logger.info("┌─── RELATED HISTORY (Embedding Semantic Search) ───")
        if related_history:
            logger.info(f"│ Found {len(related_history)} semantically related past messages")
            for i, msg in enumerate(related_history[:10]):  # Log top 10
                role = "USER" if msg.get("role") == "user" else "ASSISTANT"
                content = msg.get("content", "")[:100].replace('\n', ' ')
                score = msg.get("score", 0)
                conv_id = msg.get("conversation_id", "?")[:8]
                logger.info(f"│ [{i+1}] {role} (conv: {conv_id}..., score: {score:.2%}): {content}...")
            if len(related_history) > 10:
                logger.info(f"│ ... and {len(related_history) - 10} more results")
        else:
            logger.info("│ (No semantically related past messages found)")
        logger.info("└───────────────────────────────────────────────────")
        
        # 6. Current Request
        logger.info("┌─── CURRENT REQUEST ───")
        logger.info(f"│ User Input: {ctx.state.user_input}")
        logger.info(f"│ Detected Intent: {ctx.state.intent.intent_type.value if ctx.state.intent else 'None'}")
        logger.info(f"│ Extracted Entities: {ctx.state.entities}")
        logger.info(f"│ Is Meta Question: {is_meta_question}")
        logger.info(f"│ ReAct Mode: {ctx.state.react_mode}")
        logger.info("└───────────────────────")
        
        # 7. Tool Execution Context
        logger.info("┌─── TOOL EXECUTION CONTEXT ───")
        logger.info(f"│ Tool Used: {ctx.state.tool_name or 'None'}")
        if ctx.state.tool_result:
            logger.info(f"│ Tool Result ({len(ctx.state.tool_result)} chars):")
            for line in ctx.state.tool_result.split('\n')[:10]:
                logger.info(f"│   {line[:100]}")
            if len(ctx.state.tool_result.split('\n')) > 10:
                logger.info(f"│   ... ({len(ctx.state.tool_result.split(chr(10))) - 10} more lines)")
        else:
            logger.info("│ Tool Result: None")
        logger.info("└──────────────────────────────")
        
        # 8. Active Plan Context
        logger.info("┌─── ACTIVE PLAN CONTEXT ───")
        if ctx.state.current_plan:
            logger.info(f"│ Plan ID: {ctx.state.current_plan.id}")
            logger.info(f"│ Goal: {ctx.state.current_plan.goal.description}")
            logger.info(f"│ Status: {ctx.state.current_plan.status.value}")
            logger.info(f"│ Steps ({len(ctx.state.current_plan.steps)}):")
            for i, step in enumerate(ctx.state.current_plan.steps):
                status = "✓" if step.completed_at else "○"
                logger.info(f"│   [{status}] {i+1}. {step.step.description[:60]}")
        else:
            logger.info("│ (No active plan)")
        logger.info("└───────────────────────────")
        
        # 9. ReAct Step Results (if in ReAct mode)
        if ctx.state.react_mode and ctx.state.step_results:
            logger.info("┌─── REACT STEP RESULTS ───")
            for result in ctx.state.step_results:
                logger.info(f"│ Step {result['step_num']}: {result['step_description']}")
                logger.info(f"│   Thought: {result['thought'][:80]}...")
                logger.info(f"│   Action: {result['action']}")
                logger.info(f"│   Observation: {result['observation'][:80]}...")
            logger.info("└──────────────────────────")
        
        logger.info("=" * 80)
        logger.info("📤 FULL PROMPT SENT TO LLM:")
        logger.info("=" * 80)
        logger.info(prompt)
        logger.info("=" * 80)

        try:
            # Check if we have an event callback for streaming (group chat context)
            has_streaming_callback = ctx.deps.event_callback is not None
            
            if has_streaming_callback:
                # Use streaming coordinator (plain text output) for real-time streaming
                from agent_system.adapters.outbound.llm import create_streaming_coordinator_agent
                streaming_agent = create_streaming_coordinator_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                
                try:
                    async with streaming_agent.run_stream(prompt) as stream:
                        accumulated_text = ""
                        async for text_chunk in stream.stream_text(delta=True):
                            accumulated_text += text_chunk
                            # Emit chunk event for real-time streaming
                            await ctx.deps.emit_event("response_chunk", "GenerateResponse", text_chunk, {
                                "accumulated_length": len(accumulated_text),
                            })
                        
                        # Get the final text output
                        ctx.state.response = await stream.get_output()
                        logger.info(f"Streaming response completed, length: {len(ctx.state.response)}")
                        
                except Exception as stream_err:
                    # Fallback to non-streaming structured agent if streaming fails
                    logger.warning(f"Streaming failed, falling back to non-streaming: {stream_err}")
                    agent = create_coordinator_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                    result = await agent.run(prompt)
                    ctx.state.response = result.output.response
                    
                    if result.output.suggestions:
                        from agent_system.domain.value_objects import Suggestion
                        ctx.state.suggestions = [
                            Suggestion(
                                title=s[:50],
                                description=s,
                                relevance_score=0.7,
                                based_on=[],
                                action_type="follow_up",
                            )
                            for s in result.output.suggestions[:3]
                        ]
            else:
                # Non-group context: use structured coordinator for better responses with suggestions
                agent = create_coordinator_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                result = await agent.run(prompt)
                ctx.state.response = result.output.response
                
                if result.output.suggestions:
                    from agent_system.domain.value_objects import Suggestion
                    ctx.state.suggestions = [
                        Suggestion(
                            title=s[:50],
                            description=s,
                            relevance_score=0.7,
                            based_on=[],
                            action_type="follow_up",
                        )
                        for s in result.output.suggestions[:3]
                    ]
                
        except Exception as e:
            # Fallback response if LLM fails
            logger.error(f"Response generation LLM call failed: {type(e).__name__}: {e}")
            if ctx.state.tool_result:
                ctx.state.response = ctx.state.tool_result
            else:
                ctx.state.response = f"I understand you're asking about: {ctx.state.user_input[:100]}. Let me help you with that."
            
            # Add plan status
            if ctx.state.current_plan and ctx.state.current_plan.is_complete:
                ctx.state.response += "\n\nYour plan has been completed successfully!"
            elif ctx.state.current_plan:
                ctx.state.response += f"\n\nPlan progress: {ctx.state.current_plan.progress:.0f}%"
        
        await ctx.deps.emit_event("node_complete", "GenerateResponse", "Response generated", {
            "response_length": len(ctx.state.response),
        })
        return FinalizeKnowledge()


@dataclass
class FinalizeKnowledge(BaseNode[WorkflowState, AgentDependencies, WorkflowResult]):
    """Finalize knowledge graph updates and generate suggestions."""

    async def run(
        self,
        ctx: GraphRunContext[WorkflowState, AgentDependencies],
    ) -> End[WorkflowResult]:
        """Update knowledge graph and return final result."""
        from agent_system.domain.value_objects import Suggestion
        from agent_system.domain.entities.user import LearnedPattern
        from agent_system.adapters.outbound.llm import create_knowledge_agent
        
        await ctx.deps.emit_event("node_start", "FinalizeKnowledge", "Learning from conversation...")
        
        # Extract knowledge from this exchange to remember for future conversations
        try:
            agent = create_knowledge_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
            
            # Build context for knowledge extraction
            recent_exchange = f"User said: {ctx.state.user_input}\nAssistant responded: {ctx.state.response}"
            knowledge_result = await agent.run(recent_exchange)
            
            # Store any new learned patterns about the user
            if knowledge_result.output.entities:
                for entity in knowledge_result.output.entities[:3]:  # Limit to 3 new patterns
                    # Check if we already know this
                    existing = [p.description.lower() for p in ctx.state.user.learned_patterns]
                    if entity.lower() not in " ".join(existing):
                        new_pattern = LearnedPattern(
                            pattern_type="fact",
                            description=entity,
                            confidence=0.8,
                        )
                        ctx.state.user = ctx.state.user.add_learned_pattern(new_pattern)
            
            # Store topics as learned patterns
            if knowledge_result.output.topics:
                for topic in knowledge_result.output.topics[:2]:
                    existing = [p.description.lower() for p in ctx.state.user.learned_patterns]
                    topic_desc = f"Interested in {topic}"
                    if topic_desc.lower() not in " ".join(existing):
                        new_pattern = LearnedPattern(
                            pattern_type="interest",
                            description=topic_desc,
                            confidence=0.6,
                        )
                        ctx.state.user = ctx.state.user.add_learned_pattern(new_pattern)
            
            # Persist updated user with new patterns
            await ctx.deps.user_repository.update(ctx.state.user)
            
        except Exception as e:
            # Knowledge extraction is optional - don't break the workflow
            logger.debug(f"Knowledge extraction skipped: {e}")

        # Generate suggestions if not already set
        if not ctx.state.suggestions:
            suggestions = []
            
            if ctx.state.intent:
                if ctx.state.intent.intent_type.value == "question":
                    suggestions.append(Suggestion(
                        title="Learn more",
                        description="Would you like me to search for more information on this topic?",
                        relevance_score=0.7,
                        based_on=[],
                        action_type="web_search",
                    ))
                elif ctx.state.intent.intent_type.value == "task":
                    suggestions.append(Suggestion(
                        title="Create a plan",
                        description="I can create a detailed plan to accomplish this task.",
                        relevance_score=0.8,
                        based_on=[],
                        action_type="create_plan",
                    ))
            
            suggestions.append(Suggestion(
                title="Fun fact",
                description="Want to hear a random interesting fact?",
                relevance_score=0.5,
                based_on=[],
                action_type="random_fact",
            ))
            
            ctx.state.suggestions = suggestions
        
        # Mark workflow as complete
        ctx.state.is_complete = True
        
        # Record interaction to knowledge graph (entities, intents, and tools)
        # This builds topic-to-topic relationships for richer graph structure
        if ctx.deps.knowledge_graph_port:
            try:
                # Collect entities from the conversation
                entities_to_record = list(ctx.state.entities) if ctx.state.entities else []
                
                # Also extract entities from knowledge agent if available
                try:
                    from agent_system.adapters.outbound.llm import create_knowledge_agent
                    agent = create_knowledge_agent(ctx.deps.default_model, ctx.deps.openai_api_key)
                    recent_exchange = f"User said: {ctx.state.user_input}\nAssistant responded: {ctx.state.response[:500]}"
                    knowledge_result = await agent.run(recent_exchange)
                    
                    if knowledge_result.output.entities:
                        entities_to_record.extend(knowledge_result.output.entities[:5])
                    if knowledge_result.output.topics:
                        entities_to_record.extend(knowledge_result.output.topics[:3])
                except Exception as ke:
                    logger.debug(f"Knowledge extraction for graph failed: {ke}")
                
                # Deduplicate and clean entities
                seen = set()
                clean_entities = []
                for e in entities_to_record:
                    e_lower = e.lower().strip()
                    if e_lower and e_lower not in seen and len(e_lower) > 1:
                        seen.add(e_lower)
                        clean_entities.append(e.strip())
                
                # Build summary
                summary = ctx.state.user_input[:100]
                if ctx.state.tool_name:
                    summary = f"Used {ctx.state.tool_name}: {summary}"
                
                # Record to knowledge graph
                await ctx.deps.knowledge_graph_port.record_interaction(
                    user_id=ctx.state.user.id,
                    conversation_id=str(ctx.state.conversation.id),
                    summary=summary,
                    intents=[ctx.state.intent.intent_type.value] if ctx.state.intent else [],
                    entities=clean_entities[:8],  # Limit to 8 entities
                    tools_used=[ctx.state.tool_name] if ctx.state.tool_name else [],
                    user_label=ctx.state.user.email,
                )
                logger.debug(f"Recorded interaction with {len(clean_entities)} entities")
            except Exception as e:
                logger.debug(f"Failed to record interaction: {e}")
        
        # Extract social graph entities (people, pets, locations, preferences)
        if ctx.deps.knowledge_graph_port:
            try:
                from agent_system.adapters.outbound.llm.knowledge_extractor import extract_knowledge_from_text
                
                # Build context from recent conversation
                history_messages = ctx.state.conversation.get_context_messages()
                recent_context = None
                if history_messages:
                    recent_context = [
                        {"role": m.role.value, "content": m.content.text[:300]}
                        for m in history_messages[-5:]
                    ]
                
                # Get existing entities for better resolution
                existing_persons = await ctx.deps.knowledge_graph_port.list_known_people(ctx.state.user.id)
                existing_pets = await ctx.deps.knowledge_graph_port.list_pets(ctx.state.user.id)
                existing_locations = await ctx.deps.knowledge_graph_port.list_locations(ctx.state.user.id)
                
                person_names = [p.get("name", "") for p in existing_persons] if existing_persons else []
                pet_names = [p.get("name", "") for p in existing_pets] if existing_pets else []
                location_names = [l.get("name", "") for l in existing_locations] if existing_locations else []
                
                # Extract entities from the exchange
                content = f"{ctx.state.user_input}\n{ctx.state.response[:500]}"
                entity_result = await extract_knowledge_from_text(
                    content,
                    api_key=ctx.deps.openai_api_key,
                    context=recent_context,
                    existing_persons=person_names,
                    existing_pets=pet_names,
                    existing_locations=location_names,
                )
                
                # Store extracted persons
                for person in entity_result.persons:
                    if person.confidence >= 0.7:
                        await ctx.deps.knowledge_graph_port.store_person(
                            user_id=ctx.state.user.id,
                            name=person.name,
                            aliases=person.aliases,
                            relationship_type=person.relationship_type,
                            context_notes=person.context_notes,
                        )
                        logger.debug(f"Stored person: {person.name}")
                
                # Store extracted pets
                for pet in entity_result.pets:
                    if pet.confidence >= 0.7:
                        await ctx.deps.knowledge_graph_port.store_pet(
                            user_id=ctx.state.user.id,
                            name=pet.name,
                            aliases=pet.aliases,
                            species=pet.species,
                            breed=pet.breed,
                            personality=pet.traits,  # ExtractedPet uses 'traits' field
                            food_preferences=pet.food_preferences,
                        )
                        logger.info(f"Stored pet: {pet.name} (species={pet.species}, confidence={pet.confidence})")
                
                # Store extracted locations
                for location in entity_result.locations:
                    if location.confidence >= 0.7:
                        await ctx.deps.knowledge_graph_port.store_location(
                            user_id=ctx.state.user.id,
                            name=location.name,
                            location_type=location.location_type,
                            city=location.city,
                            neighborhood=location.neighborhood,
                        )
                        logger.debug(f"Stored location: {location.name}")
                
                # Store extracted preferences
                for pref in entity_result.preferences:
                    await ctx.deps.knowledge_graph_port.store_preference(
                        user_id=ctx.state.user.id,
                        category=pref.category,
                        value=pref.value,
                        sentiment=pref.sentiment,
                        confidence=pref.confidence,
                        source_conversation=str(ctx.state.conversation.id),
                    )
                    logger.debug(f"Stored preference: {pref.category}/{pref.value}")
                
                # Create relationships between entities
                for rel in entity_result.relationships:
                    try:
                        await ctx.deps.knowledge_graph_port.link_entities(
                            user_id=ctx.state.user.id,
                            from_entity=rel.from_entity,
                            from_type=rel.from_type,
                            to_entity=rel.to_entity,
                            to_type=rel.to_type,
                            relationship=rel.relationship,
                        )
                        logger.debug(f"Linked: {rel.from_entity} -{rel.relationship}-> {rel.to_entity}")
                    except Exception as rel_err:
                        logger.debug(f"Failed to link entities: {rel_err}")
                
                if entity_result.persons or entity_result.pets or entity_result.locations:
                    logger.info(
                        f"Extracted social entities: {len(entity_result.persons)} people, "
                        f"{len(entity_result.pets)} pets, {len(entity_result.locations)} locations"
                    )
                else:
                    logger.info(
                        f"Entity extraction completed: 0 stored "
                        f"(extracted: {len(entity_result.persons)} persons, "
                        f"{len(entity_result.pets)} pets, {len(entity_result.locations)} locations) "
                        f"reasoning: {entity_result.reasoning[:150] if entity_result.reasoning else 'none'}"
                    )
                    
            except Exception as entity_err:
                logger.warning(
                    f"Social entity extraction failed (will not store person/pet/location): {entity_err}",
                    exc_info=True,
                )
        
        # Store message embeddings for semantic search
        # Use per-user API key to create embedding adapter dynamically
        if ctx.deps.knowledge_graph_port:
            try:
                import uuid
                from agent_system.adapters.outbound.embedding import OpenAIEmbeddingAdapter
                
                # Get embedding adapter - use existing or create with user's API key
                embedding_adapter = ctx.deps.embedding_port
                if not embedding_adapter and ctx.deps.openai_api_key:
                    embedding_adapter = OpenAIEmbeddingAdapter(api_key=ctx.deps.openai_api_key)
                
                if not embedding_adapter:
                    logger.debug("No API key available for embeddings in individual chat")
                else:
                    # Embed and store user message
                    user_embedding = await embedding_adapter.embed(ctx.state.user_input)
                    user_msg_id = str(uuid.uuid4())
                    await ctx.deps.knowledge_graph_port.store_message_embedding(
                        user_id=ctx.state.user.id,
                        conversation_id=str(ctx.state.conversation.id),
                        message_id=user_msg_id,
                        content=ctx.state.user_input,
                        role="user",
                        embedding=user_embedding.embedding,
                        metadata={"intent": ctx.state.intent.intent_type.value if ctx.state.intent else None},
                    )
                    logger.info(f"Stored user message embedding: {user_msg_id}")
                    
                    # Embed and store assistant response
                    assistant_embedding = await embedding_adapter.embed(ctx.state.response)
                    assistant_msg_id = str(uuid.uuid4())
                    await ctx.deps.knowledge_graph_port.store_message_embedding(
                        user_id=ctx.state.user.id,
                        conversation_id=str(ctx.state.conversation.id),
                        message_id=assistant_msg_id,
                        content=ctx.state.response,
                        role="assistant",
                        embedding=assistant_embedding.embedding,
                        metadata={
                            "tool_used": ctx.state.tool_name,
                            "intent": ctx.state.intent.intent_type.value if ctx.state.intent else None,
                        },
                    )
                    logger.info(f"Stored assistant message embedding: {assistant_msg_id}")
                    
            except Exception as e:
                logger.debug(f"Failed to store embeddings: {e}")
        
        # Emit final response event
        await ctx.deps.emit_event("response", "FinalizeKnowledge", "Workflow complete", {
            "response": ctx.state.response,
            "suggestions": [{"title": s.title, "description": s.description} for s in ctx.state.suggestions],
            "tools_used": [ctx.state.tool_name] if ctx.state.tool_name else [],
        })
        
        # Create and return result
        result = WorkflowResult.from_state(ctx.state)
        return End(result)
