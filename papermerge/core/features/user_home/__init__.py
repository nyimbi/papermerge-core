# User Home Page Feature — only export view schemas to avoid circular imports
# UserHomeService is imported directly where needed to avoid engine→all_models cycle
from .views import (
	UserHomeDataOut, UserInfo, UserStats, WorkflowTaskOut, TaskAction,
	RecentDocumentOut, FavoriteItemOut, ActivityEventOut, NotificationOut,
	CalendarEventOut, RecentSearchOut, FavoriteItemCreate, TaskActionRequest,
)

__all__ = [
	'UserHomeDataOut',
	'UserInfo',
	'UserStats',
	'WorkflowTaskOut',
	'TaskAction',
	'RecentDocumentOut',
	'FavoriteItemOut',
	'ActivityEventOut',
	'NotificationOut',
	'CalendarEventOut',
	'RecentSearchOut',
	'FavoriteItemCreate',
	'TaskActionRequest',
]
