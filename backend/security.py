import bcrypt
from passlib.hash import argon2

def hash_password(password: str, algo: str = "argon2") -> str:
    if algo == "bcrypt":
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return argon2.hash(password)

def verify_password(password: str, hashed: str, algo: str) -> bool:
    if algo == "bcrypt":
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    return argon2.verify(password, hashed)
