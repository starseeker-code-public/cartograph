from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.auth.models import User
from cartograph.auth.schemas import LoginRequest, TokenResponse, UserOut
from cartograph.auth.security import create_access_token, verify_password
from cartograph.deps import CurrentUser, get_current_user, get_db
from cartograph.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.email == payload.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    token = create_access_token(user.id, user.tenant_id)
    # Cookie lets same-origin requests that can't set headers (MapLibre tile
    # fetches, <img>) authenticate; the Authorization header still wins.
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        max_age=settings.access_token_expire_minutes * 60,
    )
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie("access_token")


@router.get("/me", response_model=UserOut)
async def me(current: Annotated[CurrentUser, Depends(get_current_user)]) -> UserOut:
    return UserOut(id=current.user_id, tenant_id=current.tenant_id, email=current.email)
