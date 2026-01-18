# (c) Copyright Datacraft, 2026
"""
Billing router tests.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from papermerge.core.tests.types import AuthTestClient


async def test_get_current_usage(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test getting current usage statistics."""
	response = await auth_api_client.get("/billing/usage/current")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert "storage_bytes" in data
	assert "documents_count" in data
	assert "users_count" in data


async def test_get_usage_history(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test getting usage history."""
	response = await auth_api_client.get(
		"/billing/usage/history",
		params={"days": 30},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert "daily_usage" in data
	assert isinstance(data["daily_usage"], list)


async def test_get_cost_estimate(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test getting cost estimate."""
	response = await auth_api_client.get("/billing/cost/estimate")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert "storage_cost" in data
	assert "compute_cost" in data
	assert "total_cost" in data


async def test_list_invoices(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test listing invoices."""
	response = await auth_api_client.get("/billing/invoices")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert "items" in data
	assert "total" in data


async def test_get_billing_alerts(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test getting billing alerts."""
	response = await auth_api_client.get("/billing/alerts")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert isinstance(data, list)


async def test_create_billing_alert(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test creating a billing alert."""
	response = await auth_api_client.post(
		"/billing/alerts",
		json={
			"alert_type": "storage_threshold",
			"threshold_value": 10737418240,  # 10 GB in bytes
			"notification_emails": ["admin@example.com"],
		},
	)

	assert response.status_code == 201, response.json()
	data = response.json()
	assert data["alert_type"] == "storage_threshold"


async def test_update_billing_alert(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test updating a billing alert."""
	# First create an alert
	create_response = await auth_api_client.post(
		"/billing/alerts",
		json={
			"alert_type": "storage_threshold",
			"threshold_value": 10737418240,
			"notification_emails": ["admin@example.com"],
		},
	)
	alert_id = create_response.json()["id"]

	# Update the alert
	response = await auth_api_client.patch(
		f"/billing/alerts/{alert_id}",
		json={"threshold_value": 21474836480},  # 20 GB
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["threshold_value"] == 21474836480


async def test_delete_billing_alert(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test deleting a billing alert."""
	# First create an alert
	create_response = await auth_api_client.post(
		"/billing/alerts",
		json={
			"alert_type": "cost_threshold",
			"threshold_value": 10000,  # $100.00 in cents
			"notification_emails": ["admin@example.com"],
		},
	)
	alert_id = create_response.json()["id"]

	# Delete the alert
	response = await auth_api_client.delete(f"/billing/alerts/{alert_id}")

	assert response.status_code == 204


async def test_get_cost_breakdown_by_service(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test getting cost breakdown by service."""
	response = await auth_api_client.get(
		"/billing/cost/breakdown",
		params={"period": "month"},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert "services" in data
	assert isinstance(data["services"], list)
