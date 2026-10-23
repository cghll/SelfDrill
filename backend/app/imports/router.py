"""导入接口（docs/03 第 5 节）。"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.auth.dependencies import CurrentUser, DbSession
from app.imports import confirm as import_confirm
from app.imports import service as import_service
from app.imports.schemas import (
    ConfirmRequest,
    ConfirmResponse,
    PreviewItemPatch,
    PreviewItemPatchResponse,
    PreviewResponse,
)

router = APIRouter(tags=["imports"])


@router.post(
    "/banks/{bank_id}/imports/preview",
    response_model=PreviewResponse,
    status_code=201,
)
def create_preview(
    bank_id: str,
    current_user: CurrentUser,
    session: DbSession,
    file: UploadFile = File(...),
) -> PreviewResponse:
    return import_service.create_preview(session, current_user, bank_id, file)


@router.patch(
    "/imports/{preview_id}/items/{preview_item_id}",
    response_model=PreviewItemPatchResponse,
)
def patch_preview_item(
    preview_id: str,
    preview_item_id: str,
    payload: PreviewItemPatch,
    current_user: CurrentUser,
    session: DbSession,
) -> PreviewItemPatchResponse:
    return import_service.patch_item(
        session, current_user, preview_id, preview_item_id, payload
    )


@router.post(
    "/imports/{preview_id}/confirm",
    response_model=ConfirmResponse,
    status_code=201,
)
def confirm_import(
    preview_id: str,
    payload: ConfirmRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ConfirmResponse:
    return import_confirm.confirm_import(session, current_user, preview_id, payload)
