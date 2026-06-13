# (c) Copyright Datacraft, 2026
"""Portfolios API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import Portfolio, PortfolioAccess

router = APIRouter(
	prefix="/portfolios",
	tags=["portfolios"],
)

logger = logging.getLogger(__name__)


@router.get("/")
async def list_portfolios(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
) -> schema.PortfolioListResponse:
	"""List portfolios accessible to the user."""
	offset = (page - 1) * page_size

	conditions = [Portfolio.tenant_id == user.tenant_id]

	count_stmt = select(func.count()).select_from(Portfolio).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(Portfolio).where(and_(*conditions)).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	portfolios = result.scalars().all()

	return schema.PortfolioListResponse(
		items=[schema.PortfolioInfo.model_validate(p) for p in portfolios],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/")
async def create_portfolio(
	portfolio: schema.PortfolioCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PortfolioInfo:
	"""Create a new portfolio."""
	db_portfolio = Portfolio(
		tenant_id=user.tenant_id,
		name=portfolio.name,
		description=portfolio.description,
		portfolio_type=portfolio.portfolio_type,
		portfolio_metadata=portfolio.metadata,
		created_by=user.id,
		updated_by=user.id,
	)
	db_session.add(db_portfolio)
	await db_session.commit()
	await db_session.refresh(db_portfolio)

	return schema.PortfolioInfo.model_validate(db_portfolio)


@router.get("/{portfolio_id}")
async def get_portfolio(
	portfolio_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PortfolioDetail:
	"""Get portfolio details with cases."""
	stmt = select(Portfolio).where(
		Portfolio.id == portfolio_id,
		Portfolio.tenant_id == user.tenant_id,
	)
	portfolio = (await db_session.execute(stmt)).scalar_one_or_none()
	if not portfolio:
		raise HTTPException(status_code=404, detail="Portfolio not found")

	# Get cases
	from papermerge.core.features.cases.db.orm import Case
	stmt = select(Case).where(Case.portfolio_id == portfolio_id)
	result = await db_session.execute(stmt)
	cases = result.scalars().all()

	return schema.PortfolioDetail(
		id=portfolio.id,
		name=portfolio.name,
		description=portfolio.description,
		portfolio_type=portfolio.portfolio_type,
		metadata=portfolio.portfolio_metadata,
		case_count=len(cases),
		created_at=portfolio.created_at,
	)


@router.patch("/{portfolio_id}")
async def update_portfolio(
	portfolio_id: UUID,
	update: schema.PortfolioUpdate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PortfolioInfo:
	"""Update portfolio details."""
	stmt = select(Portfolio).where(
		Portfolio.id == portfolio_id,
		Portfolio.tenant_id == user.tenant_id,
	)
	portfolio = (await db_session.execute(stmt)).scalar_one_or_none()
	if not portfolio:
		raise HTTPException(status_code=404, detail="Portfolio not found")

	if update.name is not None:
		portfolio.name = update.name
	if update.description is not None:
		portfolio.description = update.description
	if update.metadata is not None:
		portfolio.portfolio_metadata = update.metadata

	portfolio.updated_by = user.id
	await db_session.commit()
	await db_session.refresh(portfolio)

	return schema.PortfolioInfo.model_validate(portfolio)


@router.delete("/{portfolio_id}")
async def delete_portfolio(
	portfolio_id: UUID,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete a portfolio."""
	stmt = select(Portfolio).where(
		Portfolio.id == portfolio_id,
		Portfolio.tenant_id == user.tenant_id,
	)
	portfolio = (await db_session.execute(stmt)).scalar_one_or_none()
	if not portfolio:
		raise HTTPException(status_code=404, detail="Portfolio not found")

	await db_session.delete(portfolio)
	await db_session.commit()

	return {"success": True}


@router.post("/{portfolio_id}/access")
async def grant_portfolio_access(
	portfolio_id: UUID,
	request: schema.GrantPortfolioAccessRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PortfolioAccessInfo:
	"""Grant access to a portfolio."""
	stmt = select(Portfolio).where(
		Portfolio.id == portfolio_id,
		Portfolio.tenant_id == user.tenant_id,
	)
	portfolio = (await db_session.execute(stmt)).scalar_one_or_none()
	if not portfolio:
		raise HTTPException(status_code=404, detail="Portfolio not found")

	access = PortfolioAccess(
		portfolio_id=portfolio_id,
		subject_type=request.subject_type,
		subject_id=request.subject_id,
		allow_view=request.allow_view,
		allow_download=request.allow_download,
		allow_print=request.allow_print,
		allow_edit=request.allow_edit,
		allow_share=request.allow_share,
		inherit_to_cases=request.inherit_to_cases,
		valid_from=request.valid_from,
		valid_until=request.valid_until,
		granted_by=user.id,
	)
	db_session.add(access)
	try:
		await db_session.commit()
		await db_session.refresh(access)
	except IntegrityError:
		await db_session.rollback()
		# Unique constraint hit — return the existing record
		existing_stmt = select(PortfolioAccess).where(
			PortfolioAccess.portfolio_id == portfolio_id,
			PortfolioAccess.subject_type == request.subject_type,
			PortfolioAccess.subject_id == request.subject_id,
		)
		access = (await db_session.execute(existing_stmt)).scalar_one()

	return schema.PortfolioAccessInfo.model_validate(access)


@router.get("/{portfolio_id}/cases")
async def list_portfolio_cases(
	portfolio_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
) -> schema.PortfolioCasesResponse:
	"""List cases in a portfolio."""
	from papermerge.core.features.cases.db.orm import Case
	from papermerge.core.features.cases.schema import CaseInfo

	offset = (page - 1) * page_size

	count_stmt = select(func.count()).select_from(Case).where(
		Case.portfolio_id == portfolio_id
	)
	total = await db_session.scalar(count_stmt)

	stmt = select(Case).where(
		Case.portfolio_id == portfolio_id
	).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	cases = result.scalars().all()

	return schema.PortfolioCasesResponse(
		items=[CaseInfo.model_validate(c) for c in cases],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get("/stats")
async def get_portfolio_stats(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Aggregate counts for portfolios in the user's tenant."""
	from sqlalchemy import func
	total = (await db_session.execute(
		select(func.count()).select_from(Portfolio).where(
			Portfolio.tenant_id == user.tenant_id
		)
	)).scalar_one()
	active = (await db_session.execute(
		select(func.count()).select_from(Portfolio).where(
			Portfolio.tenant_id == user.tenant_id,
			Portfolio.status == "active",
		)
	)).scalar_one()
	return {
		"total": total,
		"active": active,
		"archived": total - active,
	}
