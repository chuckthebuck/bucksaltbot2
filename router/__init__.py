"""Router package: splits the monolithic router.py into logical submodules.

Re-exports key names for backward compatibility so that ``import router``
continues to work for existing callers.
"""

import os

if not os.environ.get("NOTDEV"):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

import mwoauth  # noqa: F401
import requests  # noqa: F401
import status_updater  # noqa: F401

from app import (  # noqa: F401
    BOT_ADMIN_ACCOUNTS,
    MAX_JOB_ITEMS,
    is_maintainer,
)
from redis_state import r  # noqa: F401
from rollback_queue import (  # noqa: F401
    process_rollback_job,
    resolve_diff_rollback_job_task as resolve_diff_rollback_job,
)
from toolsdb import get_conn, get_runtime_config  # noqa: F401

from router.authz import (  # noqa: F401
    ALLOWED_GROUPS,
    EXTRA_AUTHORIZED_USERS,
    GROUP_CACHE_TTL,
    RATE_LIMIT_JOBS_PER_HOUR,
    RATE_LIMIT_TESTER_JOBS_PER_HOUR,
    USERS_GRANTED_BATCH,
    USERS_GRANTED_CANCEL_ANY,
    USERS_GRANTED_FROM_DIFF,
    USERS_GRANTED_RETRY_ANY,
    USERS_GRANTED_VIEW_ALL,
    USERS_READ_ONLY,
    USERS_TESTER,
    _CONFIG_EDIT_PRIMARY_ACCOUNT,
    _RUNTIME_AUTHZ_ALLOWED_KEYS,
    _effective_runtime_authz_config,
    _get_user_grants_payload,
    _group_cache,
    _normalize_runtime_authz_updates,
    _normalize_username,
    _persist_runtime_authz_updates,
    _runtime_authz_defaults,
    _serialize_runtime_authz_config,
    get_user_groups,
    is_bot_admin,
)
from router.diff_state import (  # noqa: F401
    _ACCOUNT_ROLLBACK_MAX_LIMIT,
    _DIFF_PAYLOAD_TTL,
    _MW_DEBUG_BODY_MAX,
    _MW_DEBUG_MAX_ENTRIES,
    _RESOLVING_TIMEOUT_SECONDS,
    _ROLLBACKABLE_WINDOW_LIMIT,
    _diff_error_key,
    _diff_payload_key,
    _load_diff_payload,
    _maybe_mark_stale_resolving_job_failed,
    _set_diff_error,
    _store_diff_payload,
    _update_diff_payload,
)
from router import module_registry as module_registry  # noqa: F401
from router.module_registry import (  # noqa: F401
    claim_next_queued_module_job_run,
    create_module_job_run,
    get_module_config,
    get_module_job_run,
    list_module_job_runs,
    request_module_job_run_cancel,
    update_module_job_run,
    upsert_module_config,
)
from router import module_runtime as module_runtime  # noqa: F401
from router.framework_config import (  # noqa: F401
    ALLOWED_GROUPS as FRAMEWORK_ALLOWED_GROUPS,
    BOT_NAME,
    DIFF_ERROR_KEY_PREFIX,
    DIFF_PAYLOAD_KEY_PREFIX,
    DOCS_URL,
    MWOAUTH_BASE_URL,
    MWOAUTH_INDEX_URL,
    RATE_LIMIT_KEY_PREFIX,
    REDIS_KEY_PREFIX,
    UNAUTHORIZED_MESSAGE,
    WIKI_API_URL,
    WORKER_HEARTBEAT_KEY,
    oauth_callback_url,
)
from router.jobs import (  # noqa: F401
    create_rollback_jobs_from_diff,
    resolve_diff_rollback_job_impl,
)
from router.permissions import (  # noqa: F401
    _can_edit_runtime_config,
    _can_manage_user_grants,
    _can_view_runtime_config,
    _check_rate_limit,
    _user_permissions,
    is_admin_user,
    is_authorized,
    is_tester,
)
from router.routes import (  # noqa: F401
    _can_actor_approve,
    _can_review_requests,
    _can_run_live,
    _parse_bool,
    app,
)
from router.wiki_api import (  # noqa: F401
    _extract_oldid,
    _normalize_target_user_input,
    _utc_now_iso,
    fetch_contribs_after_timestamp,
    fetch_diff_author_and_timestamp,
    fetch_recent_rollbackable_contribs,
    fetch_rollbackable_window_end_timestamp,
    iter_contribs_after_timestamp,
)
