"""Plan API routes."""

from fastapi import APIRouter, HTTPException, status

from agent_system.adapters.inbound.api.dependencies import (
    CurrentUserId,
    SessionDep,
    require_plan_access,
)
from agent_system.adapters.inbound.api.schemas import (
    PlanCreate,
    PlanDetail,
    PlanRead,
    PlanStepRead,
    PlanUpdate,
)
from agent_system.adapters.outbound.persistence import SQLAlchemyPlanRepository
from agent_system.domain.entities import Plan
from agent_system.domain.value_objects import (
    ConversationId,
    PlanGoal,
    PlanId,
    PlanStatus,
    PlanStep,
    UserId,
)

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanRead])
async def list_plans(
    current_user_id: CurrentUserId,
    session: SessionDep,
    conversation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PlanRead]:
    """List plans for the current user."""
    repo = SQLAlchemyPlanRepository(session)
    
    if conversation_id:
        plans = await repo.get_by_conversation(
            ConversationId.from_string(conversation_id)
        )
    else:
        plans = await repo.get_by_user(
            UserId.from_string(current_user_id),
            limit=limit,
            offset=offset,
        )
    
    return [
        PlanRead(
            id=str(plan.id),
            user_id=str(plan.user_id),
            conversation_id=str(plan.conversation_id),
            goal_description=plan.goal.description,
            status=plan.status.value,
            progress=plan.progress,
            current_step_index=plan.current_step_index,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            completed_at=plan.completed_at,
        )
        for plan in plans
    ]


@router.post("", response_model=PlanDetail, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanCreate,
    current_user_id: CurrentUserId,
    session: SessionDep,
    conversation_id: str | None = None,
) -> PlanDetail:
    """Create a new plan."""
    repo = SQLAlchemyPlanRepository(session)
    
    # Create plan goal
    goal = PlanGoal(
        description=data.goal_description,
        success_criteria=data.success_criteria,
        context={},
    )
    
    # Create plan steps
    steps = [
        PlanStep(
            description=step.description,
            order=i,
            tool_required=step.tool_required,
            dependencies=step.dependencies,
        )
        for i, step in enumerate(data.steps)
    ]
    
    # Create plan
    # Use a placeholder conversation ID if not provided
    conv_id = ConversationId.from_string(conversation_id) if conversation_id else ConversationId.generate()
    
    plan = Plan.create(
        user_id=UserId.from_string(current_user_id),
        conversation_id=conv_id,
        goal=goal,
        steps=steps,
    )
    
    await repo.save(plan)
    
    return _plan_to_detail(plan)


@router.get("/{plan_id}", response_model=PlanDetail)
async def get_plan(
    plan_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> PlanDetail:
    """Get a plan with its steps."""
    await require_plan_access(plan_id, current_user_id, session)
    
    repo = SQLAlchemyPlanRepository(session)
    plan = await repo.get(PlanId.from_string(plan_id))
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    return _plan_to_detail(plan)


@router.patch("/{plan_id}", response_model=PlanDetail)
async def update_plan(
    plan_id: str,
    data: PlanUpdate,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> PlanDetail:
    """Update a plan's status."""
    await require_plan_access(plan_id, current_user_id, session)
    
    repo = SQLAlchemyPlanRepository(session)
    plan = await repo.get(PlanId.from_string(plan_id))
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    if data.status:
        try:
            new_status = PlanStatus(data.status)
            if new_status == PlanStatus.ACTIVE:
                plan = plan.activate()
            elif new_status == PlanStatus.PAUSED:
                plan = plan.pause()
            elif new_status == PlanStatus.COMPLETED:
                plan = plan.complete()
            elif new_status == PlanStatus.CANCELLED:
                plan = plan.cancel()
            
            await repo.update(plan)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {data.status}",
            )
    
    return _plan_to_detail(plan)


@router.post("/{plan_id}/activate", response_model=PlanDetail)
async def activate_plan(
    plan_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> PlanDetail:
    """Activate a plan."""
    await require_plan_access(plan_id, current_user_id, session)
    
    repo = SQLAlchemyPlanRepository(session)
    plan = await repo.get(PlanId.from_string(plan_id))
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    plan = plan.activate()
    await repo.update(plan)
    
    return _plan_to_detail(plan)


@router.post("/{plan_id}/pause", response_model=PlanDetail)
async def pause_plan(
    plan_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> PlanDetail:
    """Pause a plan."""
    await require_plan_access(plan_id, current_user_id, session)
    
    repo = SQLAlchemyPlanRepository(session)
    plan = await repo.get(PlanId.from_string(plan_id))
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    plan = plan.pause()
    await repo.update(plan)
    
    return _plan_to_detail(plan)


@router.post("/{plan_id}/cancel", response_model=PlanDetail)
async def cancel_plan(
    plan_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> PlanDetail:
    """Cancel a plan."""
    await require_plan_access(plan_id, current_user_id, session)
    
    repo = SQLAlchemyPlanRepository(session)
    plan = await repo.get(PlanId.from_string(plan_id))
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    plan = plan.cancel()
    await repo.update(plan)
    
    return _plan_to_detail(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: str,
    current_user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete a plan."""
    await require_plan_access(plan_id, current_user_id, session)
    
    repo = SQLAlchemyPlanRepository(session)
    success = await repo.delete(PlanId.from_string(plan_id))
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )


def _plan_to_detail(plan: Plan) -> PlanDetail:
    """Convert a Plan entity to PlanDetail schema."""
    steps = [
        PlanStepRead(
            id=str(stored.id),
            description=stored.step.description,
            status=stored.step.status.value,
            order=stored.step.order,
            tool_required=stored.step.tool_required,
            result=stored.step.result,
            error=stored.step.error,
            started_at=stored.step.started_at,
            completed_at=stored.step.completed_at,
        )
        for stored in plan.steps
    ]
    
    return PlanDetail(
        id=str(plan.id),
        user_id=str(plan.user_id),
        conversation_id=str(plan.conversation_id),
        goal_description=plan.goal.description,
        status=plan.status.value,
        progress=plan.progress,
        current_step_index=plan.current_step_index,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        completed_at=plan.completed_at,
        success_criteria=plan.goal.success_criteria,
        steps=steps,
    )
