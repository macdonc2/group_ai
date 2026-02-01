"""Authentication utilities for the API."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from agent_system.composition_root.config import get_settings

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Security scheme
security = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """Data encoded in JWT token."""

    user_id: str
    email: str
    is_superuser: bool = False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)


def create_access_token(data: TokenData) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": data.user_id,
        "email": data.email,
        "is_superuser": data.is_superuser,
        "exp": expire,
    }
    
    # Use the secret_key from settings for JWT signing
    secret_key = settings.secret_key
    
    return jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenData | None:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    secret_key = settings.secret_key
    
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        is_superuser = payload.get("is_superuser", False)
        
        if user_id is None or email is None:
            return None
            
        return TokenData(
            user_id=user_id,
            email=email,
            is_superuser=is_superuser,
        )
    except JWTError:
        return None


async def get_current_user_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenData:
    """Get the current user from the JWT token.
    
    Raises HTTPException if token is missing or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if credentials is None:
        raise credentials_exception
    
    token_data = decode_access_token(credentials.credentials)
    if token_data is None:
        raise credentials_exception
    
    return token_data


async def get_optional_user_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenData | None:
    """Get the current user from the JWT token, or None if not authenticated."""
    if credentials is None:
        return None
    
    return decode_access_token(credentials.credentials)


async def require_superuser(
    token_data: Annotated[TokenData, Depends(get_current_user_token)],
) -> TokenData:
    """Require that the current user is a superuser."""
    if not token_data.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required",
        )
    return token_data


# Type aliases for dependency injection
CurrentUserToken = Annotated[TokenData, Depends(get_current_user_token)]
OptionalUserToken = Annotated[TokenData | None, Depends(get_optional_user_token)]
RequireSuperuser = Annotated[TokenData, Depends(require_superuser)]
