# Common Schemas
# ---------------
# Shared Pydantic models used across the application
#
# Response schemas:
# - ErrorResponse: error code, message, details
# - SuccessResponse: message, data (optional)
# - PaginatedResponse: data list, pagination metadata
#
# Pagination:
# - PaginationParams: page, page_size, sort_by, sort_order
# - PaginationMeta: page, page_size, total_items, total_pages
#
# Usage:
# All API responses should follow consistent format
